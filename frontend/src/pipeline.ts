import type {Run, Trace} from './types';

export const toolNames = ['create_alert', 'notify_operator', 'save_report'];
export const phaseNames = ['工具决策', '告警与通知', '生成报告', '保存完成'];

// Replay only advances when a recorded timestamp has been reached. Stream chunks
// are text fragments, never token counts or inferred performance measurements.
export function pipelineAt(trace: Trace[], elapsed: number, run?: Run) {
  const visible = trace.filter(item => item.task_ms <= elapsed);
  const completed = visible.filter(item => item.type === 'tool_complete').map(item => item.name);
  const done = !!run && run.status === 'completed' && elapsed >= run.total_task_ms;
  let phase = 0;
  if (visible.some(item => item.type === 'decision' || item.type === 'tool_start')) phase = 1;
  if (completed.includes('notify_operator') || visible.some(item => item.stage === 'report')) phase = 2;
  if (done) phase = 3;
  return {
    phase, done, completed,
    report: visible.filter(item => item.type === 'token' && item.stage === 'report').map(item => item.delta || '').join(''),
    time: run ? Math.min(elapsed, run.total_task_ms) : elapsed,
  };
}

export function reportSections(text: string) {
  return text.split(/(?=^#{1,6}\s)/m).filter(block=>block.trim()).map(block=>{
    const match=block.match(/^#{1,6}\s+([^\n]+)\n?([\s\S]*)$/);
    return {title:match?.[1]||'',body:(match?.[2]||block).replace(/\*\*/g,'').trim()};
  });
}
