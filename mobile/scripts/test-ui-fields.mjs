import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const tr = (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, k) => values[k] ?? m);
const nodes = tree => !tree || typeof tree !== 'object' ? [] : [tree, ...(tree.children ?? []).flat(Infinity).flatMap(nodes)];
function mount(file, symbol, props = {}) {
  let slot = 0, mounted = false;
  const state = [];
  const react = { createElement: (type, props, ...children) => ({ type, props, children }),
    useState(initial) { const i = slot++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
    useEffect(effect) { if (!mounted) { mounted = true; effect(); } } };
  const context = { exports: {}, Intl, require(name) {
    if (name === 'react') return react;
    if (name === '@/i18n') return { useI18n: () => ({ tr, locale: 'en' }), translate: tr };
    if (name === '@/theme/ThemeProvider') return { useTheme: () => ({ colors: {} }) };
    if (name === 'react-native') return { View: 'View', TextInput: 'TextInput', Switch: 'Switch' };
    if (name === '@/api/client') return { USE_MOCK: false, req: async path => path.endsWith('/engagement') ? { version: 1, preferences: { completion: false, weekly: true, analytics: false, weekday: 0, hour: 9, timezone: 'UTC' } } : { items: [] } };
    return { Button: 'Button', Text: 'Text', Screen: 'Screen', TopBar: 'TopBar', TimeZoneField: 'TimeZoneField' };
  } };
  vm.runInNewContext(ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText, context);
  const render = () => { slot = 0; return nodes(context.exports[symbol](props)); };
  return { render, button: label => render().find(n => n.props?.label === label) };
}
let selected;
const zone = mount('src/components/TimeZoneField.tsx', 'TimeZoneField', { value: 'UTC', disabled: false, onChange: value => { selected = value; } });
zone.button('Time zone · UTC').props.onPress();
zone.render().find(n => n.type === 'TextInput').props.onChangeText('São-invalid-zone');
assert.equal(zone.render().filter(n => n.type === 'Button' && n.props.label === 'São-invalid-zone').length, 0);
zone.render().find(n => n.type === 'TextInput').props.onChangeText('Istanbul');
zone.button('Europe/Istanbul').props.onPress();
assert.equal(selected, 'Europe/Istanbul');
assert.equal(zone.render().some(n => n.type === 'TextInput'), false);

const notifications = mount('app/notifications.tsx', 'default');
notifications.render(); await new Promise(resolve => setImmediate(resolve));
assert.equal(notifications.button('Reminder hour −1').props.disabled, true);
for (let i = 0; i < 10; i++) notifications.button('Reminder hour +1').props.onPress();
assert.equal(notifications.button('Reminder hour +1').props.disabled, true);
notifications.button('Reminder hour +1').props.onPress();
assert.ok(notifications.render().some(n => n.type === 'Text' && n.children.flat().join('').includes('19:00')));
notifications.button('Sunday').props.onPress();
assert.equal(notifications.button('Sunday').props.variant, 'selected');
console.log('UI fields: time-zone search rejects invalid choices; selection closes; reminder hours stay 09–19 and weekdays remain selectable');
