/* Untrusted source labels must remain text when opened by spreadsheet tools. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}};
vm.runInNewContext(fs.readFileSync('static/investment-research.js','utf8'),context);
const csv=context.window.InvestmentResearch.csv;
const output=csv([['name','value'],['  =HYPERLINK("https://example.invalid")','-12.34'],['\t+SUM(1,1)','8'],['\uFEFF@SUM(1,1)','0'],['普通名称','10']]);
assert.ok(output.includes('"\'  =HYPERLINK(""https://example.invalid"")","-12.34"'));
assert.ok(output.includes('"\'\t+SUM(1,1)"'));
assert.ok(output.includes('"\'\uFEFF@SUM(1,1)"'));
assert.ok(output.includes('"普通名称","10"'));
console.log('Research CSV export checks passed: whitespace formulas stay text and exact negative numbers remain numeric.');
