"""Query buttons as plain Java (4.23): only the SQL request of the DEFAULT_WHERE builder, in readable code.

A query button (WHEN-BUTTON-PRESSED -> a local LEKERDEZESI_FELTETELEK-style procedure that builds a WHERE text and
runs SET_BLOCK_PROPERTY(..., DEFAULT_WHERE, ...) / GO_BLOCK / EXECUTE_QUERY) becomes one Java method:

  - the screen's values are read from the request (the form's input fields: :XY_LAP.XY_UB_KOD ...);
  - the IFs of the trigger and of the builder are Java ifs, the constant SQL pieces are appended to the WHERE text
    (the ';' -> CHR(39) replacement is done at generation time), the :BLOCK.ITEM references in it are JDBC binds;
  - one JDBC query returns the rows of the target block (with its POST-QUERY rules, when they are translated).

The Forms plumbing is not emulated: SET_BLOCK_PROPERTY, GO_BLOCK, EXECUTE_QUERY and the navigation built-ins are
left out, a procedure called with one text (WUZENET, an alert dialog) is a message to the screen. The original Forms
code stays in the method as a comment, in a foldable //region. A value with no source on the screen is a developer
input (null, TODO). Whatever does not fit falls back to the PL/SQL query adapter (query_actions).
"""
from __future__ import annotations

import re

from .common import decode_line_escapes, java_text_block, jstr, name
from .forms_context import NORMAL_MODE, normal_mode_expression
from .plsql import Unsupported, parse

# Forms built-ins of the screen's navigation and the query plumbing: the migrated query does not need them.
IGNORED = {'GO_BLOCK', 'GO_ITEM', 'GO_RECORD', 'FIRST_RECORD', 'LAST_RECORD', 'NEXT_RECORD', 'PREVIOUS_RECORD',
           'SYNCHRONIZE', 'CLEAR_MESSAGE', 'BELL', 'SET_ITEM_PROPERTY', 'SET_BLOCK_PROPERTY', 'SHOW_VIEW', 'HIDE_VIEW',
           'CLEAR_BLOCK', 'EXECUTE_QUERY', 'DO_KEY', 'SET_WINDOW_PROPERTY', 'SHOW_WINDOW', 'HIDE_WINDOW'}
RESERVED = {'values', 'parameters', 'messages', 'where', 'params', 'rows', 'row', 'context', 'request', 'user', 'sql',
            'jdbc', 'log', 'rs', 'rowNum', 'e'}
READERS = {'text': 'text', 'number': 'number', 'datetime': 'datetime'}
JAVA_TYPES = {'text': 'String', 'number': 'java.math.BigDecimal', 'datetime': 'java.time.LocalDateTime'}
NUMBERS = {'0': 'java.math.BigDecimal.ZERO', '1': 'java.math.BigDecimal.ONE', '10': 'java.math.BigDecimal.TEN'}
MIRROR = {'=': '=', '<>': '<>', '!=': '<>', '<': '>', '>': '<', '<=': '>=', '>=': '<='}
BIND = re.compile(r':([A-Za-z][\w$#]*(?:\.[A-Za-z][\w$#]*)?)')


def camel(text: str) -> str:
    words = [w for w in re.split(r'[^A-Za-z0-9]+', text) if w]
    result = (words[0].lower() + ''.join(w[:1].upper() + w[1:].lower() for w in words[1:])) if words else 'value'
    return result if re.match(r'[a-z]', result) else 'v' + result


class Builder:
    """The trigger and its builder procedure as Java statements, with the values and binds they need."""

    def __init__(self, model: dict, trigger: dict, units: dict):
        self.model, self.units = model, units
        self.block = (trigger.get('block') or '').upper()
        self.items = {b['name']: {i['name']: i for i in b['items'] if i['kind'] != 'button'} for b in model['blocks']}
        self.reads = {}  # source -> {variable, type, java}
        self.inputs = []  # developer inputs: values with no source on the screen
        self.binds = {}  # source -> JDBC parameter (the variable)
        self.taken = set(RESERVED)
        self.builder = None  # the local procedure that builds the WHERE
        self.target = self.order = None
        self.executed = False
        self.called = []  # the local procedures shown as a message
        self.left_out = []  # Forms built-ins the migrated query does not need

    # ------------------------------------------------------------------ values of the screen

    def variable(self, base: str) -> str:
        candidate, n = base, 2
        while candidate in self.taken:
            candidate, n = base + str(n), n + 1
        self.taken.add(candidate)
        return candidate

    def value(self, reference: str) -> dict:
        """The Java variable of a :BLOCK.ITEM / :GLOBAL.X ... reference: read from the request, or a developer input."""
        source = reference.lstrip(':').upper()
        if '.' not in source and self.block and source in self.items.get(self.block, {}):
            source = self.block + '.' + source
        if source in self.reads:
            return self.reads[source]
        head, _, item = source.rpartition('.')
        info = self.items.get(head, {}).get(item)
        if head in {'GLOBAL', 'PARAMETER', 'SYSTEM'}:
            read = {'variable': self.variable(camel(source)), 'type': 'text',
                    'java': f'PlsqlValues.parameter(parameters, {jstr(source)})', 'parameters': True}
        elif info is not None and info['type'] in READERS:
            same = sum(1 for block in self.items.values() if item in block) > 1
            read = {'variable': self.variable(camel(source if same else item)), 'type': info['type'], 'item': info,
                    'java': f"PlsqlValues.{READERS[info['type']]}(values, {jstr(head)}, {jstr(item)})"}
        elif info is not None:
            raise Unsupported('Nem támogatott mezőtípus a lekérdezésben: :' + source)
        else:
            reason = 'ismeretlen mező, nincs a formban' if head else 'blokk nélküli mezőhivatkozás, nem egyértelmű'
            read = {'variable': self.variable(camel(source)), 'type': 'text', 'java': 'null', 'input': reason}
            self.inputs.append({'source': source, 'variable': read['variable'], 'type': 'text', 'reason': reason})
        self.reads[source] = read
        return read

    # ------------------------------------------------------------------ conditions

    def operand(self, node: dict) -> dict:
        """{java, type, nullable, literal, checkbox} of a value in a condition."""
        if normal_mode_expression(node):
            return {'java': jstr(NORMAL_MODE), 'type': 'text', 'nullable': False, 'literal': NORMAL_MODE}
        op = node['op']
        if op == 'literal':
            if node['value'] is None or node['type'] == 'null':
                return {'java': 'null', 'type': 'null', 'nullable': True, 'literal': None}
            if node['type'] == 'number':
                return {'java': NUMBERS.get(node['value'], 'new java.math.BigDecimal(' + jstr(node['value']) + ')'),
                        'type': 'number', 'nullable': False, 'literal': node['value']}
            if node['type'] == 'text':
                return {'java': jstr(node['value']), 'type': 'text', 'nullable': False, 'literal': node['value']}
        if op == 'ref':
            read = self.value(node['name'])
            return {'java': read['variable'], 'type': read['type'], 'nullable': True, 'literal': None,
                    'checkbox': (read.get('item') or {}).get('kind') == 'checkbox'}
        if op == 'function' and node['name'] == 'NVL' and len(node['args']) == 2 and 'NVL' not in self.units:
            first, second = (self.operand(a) for a in node['args'])
            if first['type'] == second['type'] and second['literal'] is not None:
                return {'java': f"java.util.Objects.requireNonNullElse({first['java']}, {second['java']})",
                        'type': first['type'], 'nullable': False, 'literal': None}
        raise Unsupported('A lekérdezőgomb feltétele nem fordítható egyszerű Java-feltételre: ' + str(node.get('name', op)))

    def compare(self, operator: str, left: dict, right: dict) -> str:
        if left['literal'] is not None and right['literal'] is None:
            left, right, operator = right, left, MIRROR[operator]
        operator = MIRROR[operator] if operator == '!=' else operator
        if left['literal'] is not None and right['literal'] is not None:
            if operator not in {'=', '<>'} or left['type'] != right['type']:
                raise Unsupported('Két állandó összehasonlítása.')
            return 'true' if (left['literal'] == right['literal']) == (operator == '=') else 'false'
        if 'null' in {left['type'], right['type']}:
            return 'false'  # a comparison with NULL is never true
        value, guard = left['java'], (left['java'] + ' != null && ') if left['nullable'] else ''
        if right['literal'] is not None:
            if left['type'] == 'text':
                text = right['literal'] if right['type'] == 'text' else str(right['literal'])  # a CHAR checkbox vs 1
                if operator == '=':
                    return f'{jstr(text)}.equals({value})'
                if operator == '<>':
                    return f'{guard}!{jstr(text)}.equals({value})'
                if right['type'] == 'text':
                    return f"{guard}{value}.compareTo({jstr(text)}) {operator} 0"
            elif left['type'] == 'number' and right['type'] == 'number':
                if operator == '=' and left.get('checkbox') and re.fullmatch(r'\d+', right['literal']):
                    return f"{right['java']}.equals({value})"  # the screen sends the checkbox value as written
                return f"{guard}{value}.compareTo({right['java']}) {'!=' if operator == '<>' else operator} 0"
            raise Unsupported('Típuseltérés a lekérdezőgomb feltételében: ' + left['type'] + ' / ' + right['type'])
        if left['type'] != right['type']:
            raise Unsupported('Típuseltérés a lekérdezőgomb feltételében: ' + left['type'] + ' / ' + right['type'])
        guards = guard + ((right['java'] + ' != null && ') if right['nullable'] else '')
        if left['type'] == 'text' and operator in {'=', '<>'}:
            return f"{guards}{'' if operator == '=' else '!'}{value}.equals({right['java']})"
        return f"{guards}{value}.compareTo({right['java']}) {'!=' if operator == '<>' else operator} 0"

    def condition(self, node: dict, top: bool = True) -> str:
        op = node['op']
        if op == 'is_null':
            return self.operand(node['value'])['java'] + (' != null' if node['negated'] else ' == null')
        if op == 'unary' and node['operator'] == 'NOT':
            return '!(' + self.condition(node['value'], True) + ')'
        if op == 'binary' and node['operator'] == 'AND':
            return self.condition(node['left'], False) + ' && ' + self.condition(node['right'], False)
        if op == 'binary' and node['operator'] == 'OR':
            text = self.condition(node['left'], True) + ' || ' + self.condition(node['right'], True)
            return text if top else '(' + text + ')'
        if op == 'binary' and node['operator'] in MIRROR:
            return self.compare(node['operator'], self.operand(node['left']), self.operand(node['right']))
        if op == 'literal' and node['type'] == 'boolean':
            return str(node['value']).lower()
        raise Unsupported('A lekérdezőgomb feltétele nem fordítható egyszerű Java-feltételre: ' + str(node.get('operator', op)))

    # ------------------------------------------------------------------ statements

    def message(self, node: dict) -> str | None:
        """MESSAGE('...') or a procedure called with one text (WUZENET, an alert dialog): a message to the screen."""
        args = node['args']
        if node['op'] != 'call' or len(args) != 1 or args[0]['op'] != 'literal' or args[0]['type'] != 'text':
            return None
        # not a reviewed database procedure (that may do real work) and not another Forms built-in
        from .discovery import FORMS_BUILTINS
        if node['name'] != 'MESSAGE' and (node['name'] in self.model.get('procedures', {})
                                          or node['name'] in FORMS_BUILTINS and node['name'] not in self.units):
            return None
        if node['name'] != 'MESSAGE' and node['name'] not in self.called:
            self.called.append(node['name'])
        return f"messages.add({jstr(args[0]['value'])});"

    def statements(self, nodes: list, indent: str, builder: dict | None = None) -> list[str]:
        lines = []
        for node in nodes:
            op = node['op']
            if op == 'noop':
                continue
            if op == 'block':
                if node.get('handlers'):
                    raise Unsupported('Kivételkezelő a lekérdezőgombban.')
                lines += self.statements(node['body'], indent, builder)
            elif op == 'if':
                for index, branch in enumerate(node['branches']):
                    lines.append(indent + ('if (' if index == 0 else '} else if (') + self.condition(branch['condition']) + ') {')
                    lines += self.statements(branch['body'], indent + '    ', builder)
                if node['else']:
                    lines.append(indent + '} else {')
                    lines += self.statements(node['else'], indent + '    ', builder)
                lines.append(indent + '}')
            elif op == 'abort':
                lines.append(indent + 'return new PageResult<>(null, messages);')
            elif op == 'local_assign' and builder and node['variable'].upper() == builder['variable'].upper():
                append, expression = self.text(node['value'], builder, indent)
                lines.append(indent + builder['java'] + (' += ' if append else ' = ') + expression + ';')
            elif op == 'quote_replace' and builder and node['variable'].upper() == builder['variable'].upper():
                continue  # applied to the SQL pieces at generation time (Builder.piece)
            elif op == 'call' and self.message(node):
                lines.append(indent + self.message(node))
            elif op == 'call' and node['name'] in self.units and not node['args'] and builder is None:
                lines += self.inline(node['name'], indent)
            elif op == 'call' and node['name'] == 'SET_BLOCK_PROPERTY' and builder and len(node['args']) == 3:
                lines += self.block_property(node, builder, indent)
            elif op == 'call' and node['name'] in IGNORED and node['name'] not in self.units:
                if node['name'] == 'EXECUTE_QUERY' or (node['name'] == 'DO_KEY' and node['args']
                                                       and str(node['args'][0].get('value', '')).upper() == 'EXECUTE_QUERY'):
                    self.executed = True
                elif node['name'] not in self.left_out:
                    self.left_out.append(node['name'])
            else:
                raise Unsupported('A lekérdezőgombban nem lekérdezési utasítás van: ' + str(node.get('name', op)))
        return lines

    def block_property(self, node: dict, builder: dict, indent: str) -> list[str]:
        block, prop, value = node['args']
        if block['op'] != 'literal' or prop['op'] != 'symbol':
            raise Unsupported('SET_BLOCK_PROPERTY nem szó szerinti blokkal.')
        target = block['value'].upper()
        if prop['name'] == 'DEFAULT_WHERE':
            if value != {'op': 'symbol', 'name': builder['variable']} and not (
                    value['op'] == 'symbol' and value['name'].upper() == builder['variable'].upper()):
                raise Unsupported('A DEFAULT_WHERE nem a szűrőváltozót kapja.')
            if self.target not in {None, target}:
                raise Unsupported('A lekérdezőgomb több blokk DEFAULT_WHERE-jét állítja.')
            self.target = target
            return [indent + 'where = ' + builder['java'] + ';']
        if prop['name'] == 'ORDER_BY' and value['op'] == 'literal' and value['type'] == 'text':
            self.order = value['value']
            return []
        if 'SET_BLOCK_PROPERTY ' + prop['name'] not in self.left_out:
            self.left_out.append('SET_BLOCK_PROPERTY ' + prop['name'])
        return []

    # ------------------------------------------------------------------ the builder procedure

    def inline(self, unit: str, indent: str) -> list[str]:
        if self.builder is not None:
            raise Unsupported('A lekérdezőgomb több szűrőépítő eljárást vagy egyet többször hív.')
        from .query_actions import BuilderParser
        parser = BuilderParser(decode_line_escapes(self.units[unit]['text']))
        parser.need('PROCEDURE')
        parser.need(unit)
        if parser.accept('('):
            raise Unsupported('A szűrőépítő eljárás paramétert vár.')
        if not (parser.accept('IS') or parser.accept('AS')):
            raise Unsupported('A szűrőépítő eljárás IS/AS deklarációt igényel.')
        token = parser.take()
        if token.kind != 'id' or not parser.accept('VARCHAR2'):
            raise Unsupported('A szűrőépítő egy helyi VARCHAR2 változót igényel.')
        if parser.accept('('):
            parser.take()
            parser.need(')')
        parser.need(';')
        parser.need('BEGIN')
        body = parser.statements({'END', '<EOF>'})
        parser.need('END')
        parser.accept(unit)
        parser.need(';')
        parser.need('<EOF>')
        replace = [n for n in body if n['op'] == 'quote_replace']
        separator = None
        if replace:
            expr = replace[0]['value']
            if (len(replace) > 1 or expr['op'] != 'function' or expr['name'] != 'REPLACE' or len(expr['args']) != 3
                    or expr['args'][2] != {'op': 'function', 'name': 'CHR', 'args': [{'op': 'literal', 'type': 'number', 'value': '39'}]}
                    or expr['args'][1]['op'] != 'literal'):
                raise Unsupported('Csak REPLACE(szűrőváltozó, állandó jel, CHR(39)) fordítható.')
            separator = expr['args'][1]['value']
        self.builder = unit
        java = self.variable(camel(token.value))
        builder = {'unit': unit, 'variable': token.value, 'java': java, 'separator': None}
        lines = [indent + 'String ' + java + ' = "";']
        position = body.index(replace[0]) if replace else len(body)
        builder['separator'] = separator  # the pieces before the REPLACE get the quotes now
        lines += self.statements(body[:position], indent, builder)
        builder['separator'] = None
        lines += self.statements(body[position + 1:], indent, builder)
        if len(lines) > 1 and lines[1].startswith(indent + java + ' = '):  # declared with its first value
            lines[:2] = [indent + 'String ' + lines[1][len(indent):]]
        return lines

    def piece(self, text: str, builder: dict) -> str:
        """A constant SQL piece: the quote replacement applied, the :BLOCK.ITEM references made JDBC binds."""
        if builder['separator']:
            text = text.replace(builder['separator'], "'")
        if text.count("'") % 2:
            raise Unsupported('Az SQL-részlet idézőjelei nem párosak; a kötött értékek nem azonosíthatók.')
        parts = text.split("'")
        for index in range(0, len(parts), 2):  # outside the quoted literals only
            parts[index] = BIND.sub(lambda m: ':' + self.bind(m.group(1)), parts[index])
        return "'".join(parts)

    def bind(self, reference: str) -> str:
        read = self.value(reference)
        self.binds[reference.upper()] = read['variable']
        return read['variable']

    def text(self, node: dict, builder: dict, indent: str) -> tuple[bool, str]:
        """(append, Java expression) of an assignment to the filter variable: lek_sql := lek_sql || '...' is an append."""
        parts = []

        def walk(n):
            if n['op'] == 'binary' and n['operator'] == '||':
                walk(n['left'])
                walk(n['right'])
            elif n['op'] == 'literal' and n['type'] == 'text':
                parts.append(('text', self.piece(n['value'] or '', builder)))
            elif n['op'] == 'symbol' and n['name'].upper() == builder['variable'].upper():
                parts.append(('var', builder['java']))
            else:
                raise Unsupported('A DEFAULT_WHERE csak állandó SQL-szövegből építhető.')
        walk(node)
        merged = []
        for kind, value in parts:
            if kind == 'text' and merged and merged[-1][0] == 'text':
                merged[-1] = ('text', merged[-1][1] + value)
            else:
                merged.append((kind, value))
        if len(merged) == 2 and merged[0] == ('var', builder['java']) and merged[1][0] == 'text':
            return True, self.literal(merged[1][1], indent)
        return False, ' + '.join(self.literal(v, indent) if k == 'text' else v for k, v in merged) or '""'

    @staticmethod
    def literal(text: str, indent: str) -> str:
        return java_text_block(text, indent + '        ') if '\n' in text else jstr(text)


def plan(trigger: dict, source: str, model: dict, catalog: dict) -> dict:
    """The Java query of a button, or Unsupported (the PL/SQL query adapter is the fallback)."""
    from .plsql_passthrough import local_units
    from .rules import strip_framework
    if not model['blocks']:
        raise Unsupported('Nincs leképezett adatblokk.')
    units = local_units(model)
    nodes, _ = strip_framework(parse(decode_line_escapes(source)), catalog)
    builder = Builder(model, trigger, units)
    lines = builder.statements(nodes, '            ')
    if builder.builder is None:
        raise Unsupported('A gomb nem hív szűrőépítő eljárást.')
    if not builder.executed or builder.target is None:  # EXECUTE_QUERY in the builder or after it, in the trigger
        raise Unsupported('A gomb nem futtat lekérdezést (SET_BLOCK_PROPERTY DEFAULT_WHERE + EXECUTE_QUERY).')
    block = next((b for b in model['blocks'] if b['name'] == builder.target), None)
    if not block or not block['database'] or not block['db_items'] or block.get('backend_skip'):
        raise Unsupported('A lekérdezés célja nem leképezett, lekérdezhető adatblokk: ' + str(builder.target))
    from .query_actions import message_wrapper
    return {'target': builder.target, 'unit': builder.builder, 'lines': lines, 'reads': builder.reads,
            'binds': builder.binds, 'inputs': builder.inputs, 'order': builder.order, 'called': builder.called,
            'left_out': builder.left_out,
            # shown as a message, although they do more (a log table ...): their code is in the region, a TODO says so
            'more_than_message': [n for n in builder.called if n in units and not message_wrapper(units[n]['text'])]}


def region(title: str, parts: list[tuple[str, str]], indent: str) -> str:
    """The original Forms code as a comment between //region and //endregion (foldable in the IDE)."""
    lines = [indent + '//region ' + title]
    for heading, code in parts:
        lines.append(indent + '// ' + heading)
        lines += [indent + ('// ' + line.replace('\\', '[backslash]') if line.strip() else '//') for line in code.rstrip().splitlines()]
        lines.append(indent + '//')
    return '\n'.join(lines[:-1] + [indent + '//endregion']) + '\n'


def method(operation: dict, block: dict, gated: bool, log1x, user_type: str, support, model: dict, discovery: dict) -> str:
    """The generated DPS method of a Java query button."""
    from .action_scaffold import comment_lines
    from .backend_queries import QueryCompiler, RawClause, clause_body
    from .generate import column_sql, table_alias
    from .plsql_passthrough import local_units
    from .rules import JDBC_TYPES
    from .service_inline import methods
    from .xmlmodel import get
    query = operation['query_action']['java']
    trigger = next(t for t in model['triggers'] if t['owner'] == operation['action']['owner']
                   and t['event'] == operation['action']['event'])
    units = local_units(model)
    # the original code: the trigger, the builder, the message procedures, the Forms code the query leaves out
    parts = [(trigger['owner'] + ' / ' + trigger['event'] + ':', decode_line_escapes(trigger['source']))]
    parts += [(name_ + ' (helyi eljárás' + (', üzenetként jelenik meg' if name_ in query['called'] else '') + '):',
               decode_line_escapes(units[name_]['text'])) for name_ in [query['unit'], *query['called']] if name_ in units]
    todo = operation.get('query_blockers') or []
    blocking = [t for t in model['triggers'] if t['status'] == 'review' and any(d.startswith(t['id'] + ':') for d in todo)]
    parts += [(t['id'] + ' (nem fordult le; a migrált lekérdezés nem futtatja):', decode_line_escapes(t['source'])) for t in blocking]
    original = region('Eredeti Forms-kód: ' + ', '.join([trigger['owner'], query['unit'], *query['called']]), parts, '        ')
    compiler = QueryCompiler(model, block)
    relation = compiler.predicate(block.get('relation_where', ''))
    order_source = query['order'] or clause_body(get(block['properties'], 'OrderByClause'), 'ORDER', 'BY')
    try:
        order = compiler.order(order_source)
    except Unsupported:
        order = RawClause(model, block, compiler.binds).sql(order_source)
    order = order or ', '.join(i['column'] for i in block['pk']) or block['db_items'][0]['column']
    select = ('SELECT ' + ', '.join(column_sql(i) for i in block['db_items']) + ' FROM ' + block['table']
              + table_alias(block, block['table']) + ' WHERE ')
    tail = (' AND (' + relation + ')' if relation else '') + ' ORDER BY ' + order + ' OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY'
    reads = query['reads']
    values = any('parameters' not in r and 'input' not in r for r in reads.values()) or bool(compiler.binds)
    head = []
    if values:
        head.append('            var values = request.blocks() == null ? java.util.Map.<String, java.util.Map<String, String>>of() : request.blocks();')
    if any('parameters' in r for r in reads.values()):
        head.append('            var parameters = request.parameters() == null ? java.util.Map.<String, String>of() : request.parameters();')
    for source, read in reads.items():
        if 'input' in read:
            head.append(f"            // TODO: :{source} ({read['input']}): add át ennek a változónak a megfelelő értéket.")
        head.append(f"            {JAVA_TYPES[read['type']]} {read['variable']} = {read['java']};")
    head += ['            var messages = new java.util.ArrayList<String>();', '            String where = null;']
    params = [f'                    .addValue({jstr(variable)}, {variable})' for variable in dict.fromkeys(query['binds'].values())]
    for bind in compiler.binds.values():  # the master-detail relation
        owner, item = bind['source'].split('.', 1)
        value = f"PlsqlValues.{READERS[bind['item']['type']]}(values, {jstr(owner)}, {jstr(item)})"
        params.append(f"                    .addValue({jstr(bind['parameter'])}, {value}, {JDBC_TYPES[bind['item']['type']]})")
    params += ['                    .addValue("offset", request.offset())', '                    .addValue("limit", request.limit());']
    suffix = name(block['class'])
    suffix = suffix[:1].upper() + suffix[1:]
    post = methods('\n'.join(support)).get('postQuery' + suffix)
    post_call = ''
    if post:
        args = 'row, context' if 'RuleContext' in post['header'] else 'row'
        post_call = f'''            var context = new RuleContext();
            for (var row : rows) {{
                postQuery{suffix}({args});
            }}
            messages.addAll(context.messages());
'''
    guard = ''
    if gated:
        guard = '''            if (!MODULE_REVIEWED) {
                throw new ResponseStatusException(HttpStatus.NOT_IMPLEMENTED, "Ez a művelet ebben a modulban még nem érhető el.");
            }
'''
    info = [operation['action']['owner'] + ': lekérdezés a(z) ' + query['target'] + ' blokkra. A WHERE feltételt a '
            + query['unit'] + ' alapján a Java állítja össze a képernyő értékeiből, egy JDBC-lekérdezés fut.']
    if query['left_out']:
        info.append('Kimaradt Forms-hívások (a webes lekérdezésnek nem kellenek): ' + ', '.join(query['left_out']) + '.')
    if query['inputs']:
        info.append('Fejlesztői bemenet (a metódus elején, null; TODO): '
                    + ', '.join(':' + i['source'] + ' -> ' + i['variable'] for i in query['inputs']) + '.')
    for unit in query.get('more_than_message', []):
        info.append('TODO: a(z) ' + unit + ' itt csak üzenet, de a Formsban mást is csinál (az eredeti kódja a regionban).')
    for detail in todo:
        info.append('TODO: a Formsban ez is fut, a migrált lekérdezés nem: ' + detail)
    return comment_lines('\n'.join(info), '    ') + f'''
    @org.springframework.transaction.annotation.Transactional(rollbackFor = Exception.class)
    @Override
    public {operation['returns']} {operation['method']}({user_type} user, QueryActionRequest request) throws Exception {{
{original}        {log1x(operation, '() -> {')}
            if (request == null) {{
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Hiányzó kérés.");
            }}
{guard}            if (request.offset() < 0 || request.offset() > 1000000 || request.limit() < 1 || request.limit() > 200) {{
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "offset: 0..1000000, limit: 1..200 szükséges.");
            }}
{chr(10).join(head)}
{chr(10).join(query['lines'])}
            if (where == null) {{
                return new PageResult<>(null, messages);
            }}
            var params = new MapSqlParameterSource()
{chr(10).join(params)}
            var rows = jdbc.query({jstr(select)} + where + {jstr(tail)}, params, (rs, rowNum) -> map{suffix}(rs));
{post_call}            return new PageResult<>(rows, messages);
        }});
    }}'''
