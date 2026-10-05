"""Item states from the Forms code: when an input or button is disabled, hidden, required or read-only.

SET_ITEM_PROPERTY calls (ENABLED, VISIBLE/DISPLAYED, REQUIRED, UPDATE_ALLOWED /
INSERT_ALLOWED), the IF conditions around them, simple value assignments and
MESSAGE are translated to TypeScript and run at the Forms moment: form start,
value change of the item, record load of a form block, button press. A trigger
that does anything else is listed for manual review, never half-translated.
"""
from __future__ import annotations

import re

from .common import name
from .forms_context import NORMAL_MODE, normal_mode_expression
from .plsql import Unsupported, parse
from .ts_code import sq

PROPERTIES = {'ENABLED': 'enabled', 'VISIBLE': 'visible', 'DISPLAYED': 'visible', 'REQUIRED': 'required',
              'UPDATE_ALLOWED': 'editable', 'INSERT_ALLOWED': 'editable'}
VALUES = {'PROPERTY_TRUE': True, 'PROPERTY_FALSE': False, 'PROPERTY_ON': True, 'PROPERTY_OFF': False, 'TRUE': True, 'FALSE': False}
MOMENTS = {'PRE-FORM': 'init', 'WHEN-NEW-FORM-INSTANCE': 'init', 'WHEN-NEW-BLOCK-INSTANCE': 'init',
           'WHEN-NEW-RECORD-INSTANCE': 'record', 'POST-QUERY': 'record',
           'WHEN-CHECKBOX-CHANGED': 'change', 'WHEN-LIST-CHANGED': 'change', 'WHEN-RADIO-CHANGED': 'change',
           'WHEN-VALIDATE-ITEM': 'change', 'POST-CHANGE': 'change', 'WHEN-BUTTON-PRESSED': 'button'}
COMPARE = {'=': '=', '!=': '!=', '<>': '!=', '<': '<', '>': '>', '<=': '<=', '>=': '>='}


def targets(plan: dict) -> dict:
    """Rendered form controls and buttons, by Oracle owner."""
    result = {}
    for section in plan['sections']:
        if section['mode'] != 'form':
            continue
        for item in section['items']:
            if item.get('spacer') or item['widget'] in {'image', 'tree', 'unsupported'}:
                continue
            result[item['owner']] = {'region': section['key'], 'block': section['block'],
                                     'key': None if item['widget'] == 'button' else item['key'],
                                     'checkbox': [item['checked'], item['unchecked']] if item['widget'] == 'checkbox' else None}
    return result


class Translator:
    def __init__(self, block: str | None, controls: dict):
        self.block, self.controls, self.touched = block, controls, set()

    def owner(self, text: str) -> str:
        owner = text.strip().upper()
        if '.' not in owner and self.block:
            owner = self.block + '.' + owner
        return owner

    def statements(self, nodes: list, indent: str) -> list[str]:
        lines = []
        for node in nodes:
            op = node['op']
            if op == 'noop':
                continue
            if op == 'block':
                if node.get('handlers'):
                    raise Unsupported('kivételkezelő')
                lines += self.statements(node['body'], indent)
            elif op == 'if' and self.toggle(node, lines, indent):
                continue
            elif op == 'if':
                for index, branch in enumerate(node['branches']):
                    lines.append(indent + ('if (' if index == 0 else '} else if (') + self.expression(branch['condition']) + ') {')
                    lines += self.statements(branch['body'], indent + '  ')
                if node['else']:
                    lines.append(indent + '} else {')
                    lines += self.statements(node['else'], indent + '  ')
                lines.append(indent + '}')
            elif op == 'call' and node['name'] == 'SET_ITEM_PROPERTY':
                args = node['args']
                if len(args) != 3 or args[0]['op'] != 'literal' or args[0]['type'] != 'text':
                    raise Unsupported('SET_ITEM_PROPERTY nem szó szerinti mezőnévvel')
                if args[1]['op'] != 'symbol' or args[1]['name'] not in PROPERTIES:
                    raise Unsupported('SET_ITEM_PROPERTY: nem kezelt tulajdonság ' + str(args[1].get('name', '')))
                if args[2]['op'] != 'symbol' or args[2]['name'] not in VALUES:
                    raise Unsupported('SET_ITEM_PROPERTY: nem konstans érték')
                owner = self.owner(args[0]['value'])
                if owner not in self.controls:
                    lines.append(indent + '// ' + owner + ' nincs a képernyőn (rejtett vagy táblázatos mező): állapota nem jelenik meg.')
                    continue
                self.touched.add(owner)
                self.set_state(lines, indent, owner, PROPERTIES[args[1]['name']], str(VALUES[args[2]['name']]).lower())
            elif op == 'call' and node['name'] == 'MESSAGE' and node['args']:
                lines.append(indent + f"this.toast.warning('Üzenet', String({self.expression(node['args'][0])} ?? ''), true, this.toastLife.warning);")
            elif op == 'assign':
                owner = self.owner(node['target'])
                if owner not in self.controls or self.controls[owner]['key'] is None:
                    raise Unsupported('értékadás képernyőn nem szereplő mezőnek: ' + owner)
                lines.append(indent + f"this.setItemValue({sq(owner)}, {self.expression(node['value'])});")
            elif op == 'abort':
                lines.append(indent + 'return;')
            else:
                raise Unsupported('nem állapotkezelő utasítás: ' + str(node.get('name', op)))
        return lines

    def property_call(self, node: dict):
        args = node.get('args', [])
        if node['op'] != 'call' or node['name'] != 'SET_ITEM_PROPERTY' or len(args) != 3 or args[0]['op'] != 'literal' \
                or args[0]['type'] != 'text' or args[1].get('name') not in PROPERTIES or args[2].get('name') not in VALUES:
            return None
        owner = self.owner(args[0]['value'])
        return (owner, PROPERTIES[args[1]['name']], VALUES[args[2]['name']]) if owner in self.controls else None

    def toggle(self, node: dict, lines: list, indent: str) -> bool:
        # IF cond THEN property TRUE ELSE property FALSE: the property follows the condition, in one call.
        if len(node['branches']) != 1 or not node['else'] or not self.boolean(node['branches'][0]['condition']):
            return False
        then = [self.property_call(n) for n in node['branches'][0]['body'] if n['op'] != 'noop']
        other = [self.property_call(n) for n in node['else'] if n['op'] != 'noop']
        if not then or None in then or None in other or [c[:2] for c in then] != [c[:2] for c in other] \
                or any(a[2] == b[2] for a, b in zip(then, other)):
            return False
        condition = self.expression(node['branches'][0]['condition'])
        negated = '!' + condition if condition.startswith(('this.', '(')) else '!(' + condition + ')'
        for owner, state, value in then:
            self.touched.add(owner)
            self.set_state(lines, indent, owner, state, condition if value else negated)
        return True

    @staticmethod
    def boolean(node: dict) -> bool:
        if node['op'] == 'is_null' or node['op'] == 'binary' and node['operator'] in COMPARE:
            return True
        if node['op'] == 'unary' and node['operator'] == 'NOT':
            return Translator.boolean(node['value'])
        return node['op'] == 'binary' and node['operator'] in {'AND', 'OR'} \
            and Translator.boolean(node['left']) and Translator.boolean(node['right'])

    @staticmethod
    def set_state(lines: list, indent: str, owner: str, state: str, value: str) -> None:
        # Consecutive properties of the same item are one call: setItemState('B.X', { enabled: true, required: true }).
        prefix = indent + 'this.setItemState(' + sq(owner) + ', { '
        if lines and lines[-1].startswith(prefix) and lines[-1].endswith(' });'):
            states = dict(part.split(': ') for part in lines[-1][len(prefix):-4].split(', '))
            states[state] = value
            lines[-1] = prefix + ', '.join(k + ': ' + v for k, v in states.items()) + ' });'
            return
        lines.append(prefix + state + ': ' + value + ' });')

    def expression(self, node: dict) -> str:
        if normal_mode_expression(node):
            return sq(NORMAL_MODE)
        op = node['op']
        if op == 'literal':
            if node['type'] == 'null':
                return 'null'
            return node['value'] if node['type'] == 'number' else sq(node['value'])
        if op == 'ref':
            owner = self.owner(node['name'])
            if owner not in self.controls or self.controls[owner]['key'] is None:
                raise Unsupported('feltétel képernyőn nem szereplő mezőre: ' + owner)
            return f'this.stateValue({sq(owner)})'
        if op == 'is_null':
            test = f"this.isNull({self.expression(node['value'])})"
            return '!' + test if node['negated'] else test
        if op == 'unary' and node['operator'] == 'NOT':
            return '!(' + self.expression(node['value']) + ')'
        if op == 'binary' and node['operator'] in {'AND', 'OR'}:
            joiner = ' && ' if node['operator'] == 'AND' else ' || '
            return '(' + self.expression(node['left']) + joiner + self.expression(node['right']) + ')'
        if op == 'binary' and node['operator'] in COMPARE:
            return f"this.cmp({self.expression(node['left'])}, '{COMPARE[node['operator']]}', {self.expression(node['right'])})"
        if op == 'function' and node['name'] == 'NVL' and len(node['args']) == 2:
            first, second = (self.expression(a) for a in node['args'])
            return f'(this.isNull({first}) ? {second} : {first})'
        if op == 'function' and node['name'] in {'UPPER', 'LOWER', 'TRIM'} and len(node['args']) == 1:
            method = {'UPPER': 'toUpperCase', 'LOWER': 'toLowerCase', 'TRIM': 'trim'}[node['name']]
            inner = self.expression(node['args'][0])
            return f'(this.isNull({inner}) ? null : String({inner}).{method}())'
        raise Unsupported('nem fordítható feltétel: ' + str(node.get('operator', node.get('name', op))))


def analyse(plan: dict, discovery: dict, catalog: dict) -> dict:
    """Translated handlers per moment, plus a manual list with the raw state calls."""
    from .rules import strip_framework
    controls = targets(plan)
    handlers, manual, touched = [], [], set()
    for code in discovery.get('code', []):
        if code.get('kind') != 'trigger' or code.get('module_kind') != 'formmodule' or code.get('name') not in MOMENTS:
            continue
        source = code.get('source') or ''
        if 'SET_ITEM_PROPERTY' not in source.upper():
            continue
        moment = MOMENTS[code['name']]
        # Item trigger: BLOCK.ITEM; block trigger: BLOCK; form trigger: FORM.
        owner = '.'.join(p for p in (code.get('block'), code.get('item')) if p).upper() or 'FORM'
        calls = [c['text'] for c in code.get('calls', []) if c.get('name') == 'SET_ITEM_PROPERTY']
        if moment in {'change', 'button'} and owner not in controls:
            manual.append({'owner': owner, 'event': code['name'], 'reason': 'a mező/gomb nincs a képernyőn', 'calls': calls})
            continue
        try:
            translator = Translator(code.get('block'), controls)
            ast, _ = strip_framework(parse(source), catalog)
            lines = translator.statements(ast, '    ')
        except Unsupported as exc:
            manual.append({'owner': owner, 'event': code['name'], 'reason': str(exc), 'calls': calls})
            continue
        touched |= translator.touched
        handlers.append({'moment': moment, 'owner': owner, 'block': (code.get('block') or '').upper(), 'event': code['name'],
                         'method': 'state' + name(owner.replace('.', '_') + '_' + code['name'].replace('-', '_'), 'pascal'),
                         'lines': lines, 'touched': sorted(translator.touched)})
    return {'controls': controls, 'handlers': handlers, 'manual': manual, 'touched': sorted(touched),
            'regions': sorted({controls[o]['region'] for o in touched})}
