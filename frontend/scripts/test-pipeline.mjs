import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/pipeline.ts',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ES2022}});
const {pipelineAt}=await import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'));
const run={status:'completed',total_task_ms:18000};
const trace=[
  {type:'token',stage:'decision',delta:'{"create_alert":',task_ms:1000},
  {type:'decision',task_ms:6000},
  {type:'tool_start',name:'create_alert',task_ms:6001},
  {type:'tool_complete',name:'create_alert',task_ms:6005},
  {type:'tool_complete',name:'notify_operator',task_ms:6010},
  {type:'token',stage:'report',delta:'真实报告',task_ms:8000},
  {type:'tool_complete',name:'save_report',task_ms:17999},
];
test('stages follow actual trace boundaries, never future records',()=>{
  assert.equal(pipelineAt(trace,0,run).phase,0);
  assert.equal(pipelineAt(trace,5999,run).phase,0);
  assert.equal(pipelineAt(trace,6000,run).phase,1);
  assert.deepEqual(pipelineAt(trace,6004,run).completed,[]);
  assert.equal(pipelineAt(trace,6010,run).phase,2);
  assert.equal(pipelineAt(trace,17999,run).done,false);
  assert.equal(pipelineAt(trace,18000,run).phase,3);
});
test('only report text is exposed; JSON decision stays out of preview',()=>{
  assert.equal(pipelineAt(trace,7000,run).report,'');
  assert.equal(pipelineAt(trace,8000,run).report,'真实报告');
});
test('same replay clock shows ON completed while OFF still generates',()=>{
  const off={status:'completed',total_task_ms:26000};
  assert.equal(pipelineAt(trace,20000,run).done,true);
  assert.equal(pipelineAt(trace,20000,off).done,false);
  assert.equal(pipelineAt(trace,20000,run).time,18000);
  assert.equal(pipelineAt(trace,20000,off).time,20000);
});
test('failed run never becomes a completed lane',()=>{
  assert.equal(pipelineAt(trace,30000,{status:'failed',total_task_ms:10000}).done,false);
});
test('readable report sections preserve the conclusion first',async()=>{
  const {reportSections}=await import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'));
  const sections=reportSections('### 异常判断\n区域6人达到5人阈值。\n### 停留与移动分析\n5人位移明显。');
  assert.equal(sections[0].title,'异常判断');
  assert.equal(sections[0].body,'区域6人达到5人阈值。');
  assert.equal(sections[1].title,'停留与移动分析');
});
