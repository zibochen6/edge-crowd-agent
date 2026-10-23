REPORT='''面向值班人员，简短解释冻结事件，输出中文 Markdown，只写以下三段，不输出 JSON、编号、工具名或算法建议：
### 异常判断
用触发时实际人数、阈值、连续超限时长说明人数超限，不将人数超限等同危险。
### 停留与移动分析
依据轨迹汇总写位移明显、位移较小、观察不足的人数，引用最长连续可见时长。位移小不能认定长期滞留；短时观测不足以确认长期滞留或通行堵塞。不得编造动作、身份、意图，或断言无异常、安全、未发生堵塞。
### 处置建议
现场核实通行，准确引用恢复人数及持续时间，只说明满足人数告警恢复条件，现场仍需核实。不得声称已经疏散或控制设备。
每段至多两句，优先照下面的事实措辞写，避免重复（数字只来自输入，不用历史人数替代触发人数）：'''

def report_for(event):
    if event.get('settings',{}).get('report_language')=='en':return english_report_for(event)
    settings=event.get('settings',{})
    motion=event.get('behavior_evidence')
    if motion:
        observation=f'跟踪观察到{motion["moving_count"]}人位移明显、{motion["low_displacement_count"]}人位移较小。'
        if motion['insufficient_count']:observation+=f'另有{motion["insufficient_count"]}人观察不足。'
        observation+=f'最长连续可见约{motion["longest_continuous_roi_seconds"]:.2f}秒，短时观测不足以确认长期滞留或通行堵塞。'
    else:observation='缺少连续轨迹依据，无法判断移动或停留，需现场核实。'
    return REPORT+f'''
### 异常判断
触发时区域内{event['current_count']}人达到{event['threshold']}人阈值，连续超限{event['duration_above_threshold_sec']:.2f}秒，人数超限。
### 停留与移动分析
{observation}
### 处置建议
现场核实通行。人数降至{settings.get('recovery_count',3)}人及以下并持续{settings.get('recovery_seconds',2):g}秒后，才满足人数告警恢复条件，现场仍需核实。
'''

def english_report_for(event):
    settings=event.get('settings',{});motion=event.get('behavior_evidence')
    observation='No continuous tracking evidence is available; movement and dwell cannot be assessed.'
    if motion:
        observation=f'Tracking shows {motion["moving_count"]} people moving and {motion["low_displacement_count"]} {"person" if motion["low_displacement_count"]==1 else "people"} with low movement'
        if motion['insufficient_count']:observation+=f'; insufficient evidence for {motion["insufficient_count"]} people'
        observation+=f'; longest continuous visibility: {motion["longest_continuous_roi_seconds"]:.2f} s. Brief tracking cannot confirm prolonged loitering or blockage.'
    return f'''Write a concise English Markdown report for an operator about this frozen count event. Use digits for all counts and durations. Use exactly these three headings, at most two sentences each. Always include that brief tracking cannot confirm prolonged loitering or blockage. Copy only input facts; do not replace the trigger count with history. Low movement does not establish loitering. Do not infer identity, intent, fights, falls, safety, cleared risk, or the absence of blockage. Use the following factual wording; do not add technical discussion or tool names:
### Assessment
At trigger, {event['current_count']} people met the threshold of {event['threshold']} for {event['duration_above_threshold_sec']:.2f} s: the count limit was exceeded.
### Dwell and movement
{observation}
### Response
Check passage on site. Count-alert recovery requires at most {settings.get('recovery_count',3)} people for {settings.get('recovery_seconds',2):g} s; the scene still needs verification.
'''
