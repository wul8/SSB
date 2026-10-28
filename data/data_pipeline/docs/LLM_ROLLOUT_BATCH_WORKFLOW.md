# LLM Rollout 批量跑轨迹 + S5验证 — 操作手册

记录一次完整闭环跑法：切模型 → 批量rollout → 落盘verify_bundle → S5验证 → 解读结果。
每次批量出任务前直接照此执行，不用重新摸索。

## 0. 前置状态

- 脚本: `scripts/run_llm_rollout_batch_test.py`
- 核心生成器: `rollout/llm_rollout_generator.py`（`LLMRolloutGenerator`）
- 配置: `config.py` 里的 `LLM_ROLLOUT_CONFIG`
- 任务池: `generated_tasks/route_b_s2_only/{debugging,template}/*.json`
- 输出根目录: `trajectories/llm_rollout_runs/{timestamp}_{model}_seed{N}_n{count}/`（每次跑单独一个子目录，不会互相覆盖）

`_run_rollout()` 成功后会自动把 `task.json/input.xlsx/golden.xlsx/output.xlsx` 四件套落盘到同目录下的
`{sample_id}__verify_bundle/`，这是S5验证的直接输入。**只有 `rollout_success=True` 的任务才会有这个目录**——
max_turns超时或LLM中途放弃的任务不会有verify_bundle，也就无法S5验证。

## 1. 切换模型

编辑 `config.py` 的 `LLM_ROLLOUT_CONFIG["model"]`，其余字段（`max_tokens`/`temperature`/`reasoning_effort`）一般不用动。
`max_tokens` 必须 ≥ 16384——4096会被`reasoning_effort=max`的思考内容耗尽导致截断。

## 2. 启动批量跑（后台nohup，抗会话中断）

API key **绝不写进任何文件**，只通过环境变量单次注入：

```bash
cd /mnt/hhq/data/data_pipeline && \
export ROLLOUT_LLM_API_KEY="<key>" && \
nohup python3 scripts/run_llm_rollout_batch_test.py --count 15 --seed 42 --concurrency 4 \
  > /tmp/rollout_batch_<tag>.log 2>&1 & disown
```

- `--seed` 固定则任务抽样固定，方便跨模型/跨批次直接对比同一组任务。
- `--concurrency` 3-4 比较稳，太高容易把中转endpoint打出连续`content=None`重试。
- 每个bash工具调用不共享cwd，重新起终端记得带上`cd /mnt/hhq/data/data_pipeline &&`。

## 3. 轮询进度

```bash
sleep 280 && pgrep -af run_llm_rollout_batch_test.py; \
grep -c '\[OK\]\|\[FAIL\]' /tmp/rollout_batch_<tag>.log; \
grep '\[OK\]\|\[FAIL\]' /tmp/rollout_batch_<tag>.log
```

- 进程不在了且日志出现`总数: N, 成功submit: M`那一行即为跑完。
- kimi-k3单任务常见500-2700s（比deepseek-v4-flash慢很多，reasoning_effort=max导致），15题整批常需1-1.5小时，别用短超时空等。
- 失败原因基本两种：`超过max_turns(50)仍未submit`（LLM卡住/绕圈）、`LLM未调用任何工具就结束了回复`（中转端异常）。

## 4. 跑S5验证

先确认有哪些bundle（数量应等于`rollout_success=True`的任务数）：

```bash
ls -d trajectories/llm_rollout_runs/<run_dir>/*__verify_bundle
```

批量验证（结果多时用`run_in_background`+`TaskOutput`，避免默认180s超时把命令打断）：

```python
import sys, glob
sys.path.insert(0, '.')
from verify.trajectory_verifier import TrajectoryVerifier

run_dir = 'trajectories/llm_rollout_runs/<run_dir>'
bundles = sorted(glob.glob(f'{run_dir}/*__verify_bundle'))
verifier = TrajectoryVerifier()
approved = 0
for b in bundles:
    r = verifier.verify(b)
    approved += r.approved
    print(f"{b.split('/')[-1]}: approved={r.approved} accuracy={r.accuracy:.3f} reasons={r.rejection_reasons}")
print(f'---总计: {approved}/{len(bundles)} APPROVED---')
```

**坑**：临时验证脚本不要放在`/tmp`下直接跑——如果`/tmp`下恰好存在同名的`verify.py`残留文件，Python会把脚本所在目录插到`sys.path`最前面，`from verify.trajectory_verifier import ...`就会误加载那个残留文件而不是项目里的`verify`包（报错栈里会出现`/tmp/verify.py`）。把验证脚本放在项目根目录下跑（如`_s5_verify_xxx.py`，跑完记得删），或直接用下面第4.1节的封装脚本。

### 4.1 一步完成验证+分类打包（推荐）

跑完S5后，直接用`scripts/sort_verified_trajectories.py`把每个`__verify_bundle`按`approved`/`rejected`分流到两个子目录，同时把对应的轨迹json一起挪过去，并在`run_dir`下生成`verification_report.json`。这样S6装配阶段可以直接读`approved/`，不用每次重新判断哪些通过了。

```bash
python3 scripts/sort_verified_trajectories.py trajectories/llm_rollout_runs/<run_dir>
```

- 默认是**移动**（保持输出目录整洁，bundle不会重复散落在顶层）；加`--copy`改成复制，保留原始扁平结构。
- 跑完后目录结构变为：`<run_dir>/approved/*.__verify_bundle`、`<run_dir>/rejected/*__verify_bundle`，两边各自带上同名的轨迹json；顶层只剩`rollout_success=False`（没有bundle，验证不到）的轨迹json和`batch_test_summary.json`。
- 若已经用手工脚本跑过一遍S5、有现成的结果字典（比如批量很大先跑了一遍`verifier.verify()`存了json），可以跳过重新验证，直接按`approved`字段把bundle和json`shutil.move`到`approved/`/`rejected/`，没必要为了分类再重新触发一次LibreOffice重算。

## 5. 解读结果 —— 两个指标不是一回事

- **`rollout_success`**（batch summary里的"成功submit"）：LLM自己调用了`submit`工具，只代表流程走完了，**不代表答案对**。
- **S5 `approved`**：真正做对，要求 `accuracy=1.0` **且**不触碰受保护单元格 **且** 通过一致性/公式族/不变量等严格校验。

已观察到两类"submit成功但S5拒绝"的典型模式，跑批量时留意：

1. **accuracy=1.0但保护单元格违规**：答案区算对了，但顺手改了不该动的单元格（常见于debugging类任务，如`embedded_hardcodes`）。这在不同模型上重复出现过，更像任务本身的answer_position设计问题，不是模型偶发错误。
2. **accuracy=0且大量保护单元格违规**：LLM提交了一个几乎全错、改动面很大的结果但仍调用了submit——rollout层面显示"成功"，实际是无效输出。这种情况不能只看batch summary的成功率，必须过一遍S5才知道真实通过率。

因此汇报批量结果时必须给两个数字：**提交成功率**（batch summary）和**S5通过率**（approved/总任务数），后者才是真实解题能力。

## 6. 已知环境特性（不是bug，跑批量前心里有数）

- 同一模型、同一seed/count的批次，多次重跑成功率会有明显波动（实测deepseek-v4-flash在66.7%→53.3%→40.0%之间跳），这是上游中转endpoint/模型本身的不稳定性，重跑几次取平均更可信，不要用单次结果下结论。
- kimi-k3耗时显著高于deepseek-v4-flash，同样15题批量规划时间要预留够（1-1.5小时起）。
- `scratch_dir`是`tempfile.TemporaryDirectory`，`with`块退出即清空——`_save_verify_bundle()`必须在块内执行完，这是已经修好的地方，不要再改回"跑完再复制"的写法。
