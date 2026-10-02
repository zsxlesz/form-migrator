"""Validation coverage shared by the screen emitter and migration notes."""
import json

TEXT_WIDGETS = {'text', 'textarea', 'password', 'display', 'autocomplete'}
CONTROL_WIDGETS = TEXT_WIDGETS | {'number', 'date', 'datetime', 'checkbox', 'select', 'multiselect', 'radio'}
PROPERTIES = {
    'required': 'Required', 'maximum_length': 'MaximumLength', 'fixed_length': 'FixedLength',
    'minimum_length': 'MinLength (mezőhossz-JSON)',
    'minimum': 'LowestAllowedValue', 'maximum': 'HighestAllowedValue',
    'precision': 'Precision', 'scale': 'Scale', 'format_mask': 'FormatMask', 'case': 'CaseRestriction',
}


def validation_coverage(item, mode):
    """Every non-default rule has a destination or an explicit migration gap."""
    widget = item['widget']; rules = item['validation']; rows = []
    for key, prop in PROPERTIES.items():
        value = rules.get(key)
        if value is None or value == '' or key == 'required' and not value or key == 'case' and value == 'mixed':
            continue
        status = 'manual'; target = 'Nincs mezővezérlő: az adapterben kell érvényesíteni.'
        if mode == 'form' and widget in CONTROL_WIDGETS:
            if key == 'required':
                status = 'implemented'
                target = 'FormGroup: required; true és false is érvényes, null/üres nem.' if widget == 'checkbox' else 'FormBlock.validator + FormGroup: required.'
            elif key in {'maximum_length', 'fixed_length', 'minimum_length'} and widget in TEXT_WIDGETS:
                status = 'implemented'; target = 'FormBlock minLenght/maxLenght + FormGroup hosszellenőrzés.'
            elif key in {'minimum', 'maximum', 'precision', 'scale'} and widget == 'number':
                status = 'implemented'; target = 'FormGroup: pontos decimális ellenőrzés, kerekítés nélkül.'
                if item['representation'] == 'safe-integer' and key in {'minimum', 'maximum'}:
                    target += ' FormBlock min/max.'
            elif key == 'case' and widget in TEXT_WIDGETS:
                status = 'partial'; target = 'regexRule + FormGroup: kis-/nagybetű ellenőrzés. Automatikus betűátalakítás nincs; szükség esetén host adapter.'
            elif key == 'format_mask' and widget in {'date', 'datetime'} and rules['date_format']:
                status = 'implemented'; target = 'FormBlock.dateFormat=' + rules['date_format'] + '; showTime=' + str(widget == 'datetime').lower() + '.'
                if widget == 'datetime':
                    status = 'partial'; target += ' A másodpercmezőt és az óraciklust a privát naptárkomponensben ellenőrizni kell.'
            else:
                target = 'Nincs ellenőrzött FormBlock-leképezés ehhez a vezérlőhöz; host adapter szükséges.'
        elif mode == 'table':
            target = 'Csak olvasható táblázat: a szabályt és formázást a szerkesztő/backend adapterben kell átvenni.'
        elif mode == 'hidden':
            target = 'Rejtett/technikai mező: a szabály a runtime/backend adapter feladata.'
        rows.append({'owner': item['owner'], 'property': prop, 'value': value, 'status': status, 'target': target})
    return rows


def validators(item):
    """Small, explicit Angular rules, independent of the private FormBlock internals."""
    widget = item['widget']; v = item['validation']; result = []
    if widget not in CONTROL_WIDGETS:
        return result
    if v['required']:
        result.append("c => c.value === null || c.value === undefined || c.value === '' ? { required: true } : null"
                      if widget == 'checkbox' else 'Validators.required')
    if widget == 'checkbox':
        result.append("c => c.value == null || c.value === '' || typeof c.value === 'boolean' ? null : { checkbox: true }")
    if widget in TEXT_WIDGETS:
        if v.get('minimum_length') is not None and v['fixed_length'] is None: result.append('Validators.minLength(' + str(v['minimum_length']) + ')')
        if v['maximum_length'] is not None: result.append('Validators.maxLength(' + str(v['maximum_length']) + ')')
        if v['fixed_length'] is not None:
            result += ['Validators.minLength(' + str(v['fixed_length']) + ')', 'Validators.maxLength(' + str(v['fixed_length']) + ')']
        if v['case'] in {'upper', 'lower'}:
            method = 'toUpperCase' if v['case'] == 'upper' else 'toLowerCase'
            result.append("c => typeof c.value === 'string' && c.value !== c.value." + method + '() ? { caseRestriction: true } : null')
    if widget == 'number':
        args = {k: v[src] for k, src in [('min', 'minimum'), ('max', 'maximum'), ('precision', 'precision'), ('scale', 'scale')] if v[src] is not None}
        args['integer'] = item['representation'] == 'safe-integer'
        result.append('this.numberValidator(' + json.dumps(args) + ')')
    if widget in {'date', 'datetime'}:
        result.append("c => c.value == null || c.value === '' || c.value instanceof Date && Number.isFinite(c.value.getTime()) ? null : { date: true }")
    return list(dict.fromkeys(result))


NUMBER_VALIDATOR = r'''  private numberValidator(rule: { min?: string; max?: string; precision?: number; scale?: number; integer: boolean }): ValidatorFn {
    const decimal = (text: string) => {
      if (text.length > 260) return null;
      const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
      return match ? { digits: BigInt(match[2] + (match[3] ?? '')) * (match[1] === '-' ? -1n : 1n),
        scale: (match[3] ?? '').length, integral: match[2].replace(/^0+/, '').length } : null;
    };
    const minimum = rule.min === undefined ? null : decimal(rule.min);
    const maximum = rule.max === undefined ? null : decimal(rule.max);
    return control => {
      const value: unknown = control.value;
      if (value == null || value === '') return null;
      if (rule.integer ? !Number.isSafeInteger(value) : typeof value !== 'string') return { number: true };
      const parsed = decimal(String(value));
      if (!parsed) return { number: true };
      const compare = (bound: NonNullable<ReturnType<typeof decimal>>) => {
        const scale = Math.max(parsed.scale, bound.scale);
        const a = parsed.digits * 10n ** BigInt(scale - parsed.scale), b = bound.digits * 10n ** BigInt(scale - bound.scale);
        return a < b ? -1 : a > b ? 1 : 0;
      };
      if (rule.scale !== undefined && parsed.scale > rule.scale) return { scale: true };
      if (rule.precision !== undefined && parsed.integral + (rule.scale ?? parsed.scale) > rule.precision) return { precision: true };
      if (minimum && compare(minimum) < 0) return { min: { min: rule.min, actual: value } };
      if (maximum && compare(maximum) > 0) return { max: { max: rule.max, actual: value } };
      return null;
    };
  }'''
