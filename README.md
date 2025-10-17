# KV Cache 策略评测说明

本文档说明如何使用本仓库对 KV Cache 策略进行简单评测，并产出命中率等指标。

## 目录结构

- `kvcachepolicy.py`：缓存淘汰策略（当前实现为 FIFO，内部仅调用 store 的 `add/delete`）。
- `kvstore.py`：简易 KV 缓存存储抽象，支持容量控制与增删查（容量在此处设定并强制）。
- `test.py`：评测脚本，读取输入数据并计算命中率。
- `input_samples/`：示例输入数据。

## 输入数据格式

每一行都是一条请求/访问记录，格式类似：`{prefix_hash_id 列表} type`

示例（`input_samples/sample1`）：

```
{1,2,3,4} 1
{1,2,3,4,5} 1
{1,2,6} 2
```

说明：
- 每条记录的花括号内是该请求的 `prefix_hash_id` 访问序列；空格后的最后一个整数是该请求的 `type`。
- 评测时会按序逐个访问花括号内的 `prefix_hash_id`，对每次访问统计命中或未命中，并根据所选策略进行插入/淘汰。

## 运行评测

评测流程现在由一个配置文件 `config/test.yaml` 驱动。您需要在此文件中定义要测试的数据集以及每个数据集对应的容量列表。

1.  **配置测试任务**

    编辑 `config/test.yaml` 文件。`tests` 列表下的每个条目都代表一个测试任务：
    - `file`: `input_samples` 目录下的样本文件名。
    - `capacities`: 一个或多个要在此样本上测试的容量值。脚本会自动按从小到大的顺序进行测试。

    示例 `config/test.yaml`:
    ```yaml
    tests:
      - file: "sample1"
        capacities: [3, 5, 10]

      - file: "conversation_trace"
        capacities: [1000, 5000, 10000, 20000]
    ```

2.  **执行评测**

    配置完成后，直接运行评测脚本即可：
    ```bash
    python3 test.py
    ```
    脚本将自动加载 [test.yaml](http://_vscodecontentref_/1) 并执行其中定义的所有测试。

    如果您想使用其他配置文件，可以将其路径作为参数传入：
    ```bash
    python3 test.py path/to/your/config.yaml
    ```

## 输出说明

脚本会为每个测试的数据集输出两类结果：

1.  **控制台输出**:
    对于配置文件中定义的每个数据集和容量组合，都会打印详细的统计指标。
    ```
    ==== Testing Dataset: conversation_trace ====
      --- Running with capacity: 1000 ---
        Total requests:   288,500
        Hits:             2,004
        Misses:           286,496
        Hit Ratio:        0.69497%
        Time elapsed:     0.29680s
    ```

2.  **图表输出**:
    为每个数据集生成一张命中率（Hit Ratio）随容量（Capacity）变化的折线图。
    - 图表保存在 [output](http://_vscodecontentref_/2) 目录下。
    - 文件名包含数据集名称和运行时间戳，以防止覆盖，例如 `conversation_trace_20251017_143000.png`。

## 请自行预处理一下样例，可用于测试

https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon
https://github.com/kvcache-ai/Mooncake/tree/main/FAST25-release/traces
