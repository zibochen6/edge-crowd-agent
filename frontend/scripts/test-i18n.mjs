import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/translations.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ES2022}});
const {translate,english,validLanguage}=await import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'));
test('both languages format the same detection facts without mutating them',()=>{
 const facts={p0:6,p1:5};
 assert.equal(translate('en','触发时 {p0} 人 · 阈值 ≥ {p1} 人',facts),'At trigger: 6 people · Threshold ≥ 5');
 assert.equal(translate('zh','触发时 {p0} 人 · 阈值 ≥ {p1} 人',facts),'触发时 6 人 · 阈值 ≥ 5 人');
 assert.deepEqual(facts,{p0:6,p1:5});
});
test('unsupported saved languages fall back to Chinese; unknown diagnostic text stays intact',()=>{
 assert.equal(validLanguage('en'),'en');assert.equal(validLanguage('de'),'zh');assert.equal(validLanguage(null),'zh');
 assert.equal(translate('en','server-specific trace 123'),'server-specific trace 123');
});
test('all UI translation calls and pipeline stages have English messages',()=>{
 const missing=[];
 for(const file of ['main.tsx','PipelineLane.tsx']){
  const code=readFileSync(new URL('../src/'+file,import.meta.url),'utf8');
  const sf=ts.createSourceFile(file,code,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const visit=node=>{if(ts.isCallExpression(node)&&node.expression.getText(sf)==='t'&&ts.isStringLiteral(node.arguments[0])&&/[\u3400-\u9fff]/u.test(node.arguments[0].text)&&!(node.arguments[0].text in english))missing.push(node.arguments[0].text);ts.forEachChild(node,visit)};visit(sf);
 }
 for(const key of ['工具决策','告警与通知','生成报告','保存完成'])assert.ok(key in english);
 assert.deepEqual(missing,[]);
});
