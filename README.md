# KV Cache 策略评测说明

本文档说明如何使用本仓库对 KV Cache 策略进行简单评测，并产出命中率等指标。

## 目录结构

- `kvcachepolicy.py`：缓存淘汰策略（当前实现为 FIFO，内部仅调用 store 的 `add/delete`）。
- `kvstore.py`：简易 KV 缓存存储抽象，支持容量控制与增删查（容量在此处设定并强制）。
- `test.py`：评测脚本，读取输入数据并计算命中率。
- `input_samples/`：示例输入数据。

## 输入数据格式

输入文件不再包含容量信息。每一行都是一条请求/访问记录，格式如下：

`{prefix_hash_id 列表} type`

示例（`input_samples/sample1`）：

```
{1,2,3,4} 1
{1,2,3,4,5} 1
{1,2,6} 2
```

说明：
- 缓存容量现在通过命令行参数指定。
- 每条记录的花括号内是该请求的 `prefix_hash_id` 访问序列；空格后的最后一个整数是该请求的 `type`。
- 评测时会按序逐个访问花括号内的 `prefix_hash_id`，对每次访问统计命中或未命中，并根据所选策略进行插入/淘汰。

## 运行评测

评测脚本现在通过命令行参数来控制。

- **评测所有样本文件**（默认容量见文件args）：
  ```bash
  python3 test.py
  ```

- **评测所有样本文件，并指定一个统一的容量**：
  ```bash
  python3 test.py --capacity 1000
  ```

- **仅评测单个指定的样本文件**：
  ```bash
  python3 test.py --sample sample1 --capacity 500
  ```

- **为多个样本文件分别指定容量**：
  （假设 `input_samples` 目录下按字母顺序有 `sample1`, `sample2` 两个文件）
  ```bash
  python3 test.py --capacity 500 1000
  ```

## 输出说明

脚本会为每个测试的样本输出如下指标：

- `Total requests`: 总请求块数
- `Hits`: 命中次数
- `Misses`: 未命中次数
- `Hit Ratio`: 命中率 (`hits/total`)
- `Time elapsed`: 运行耗时

示例输出：

```
=== Testing Sample: conversation_trace (capacity=1000) ===
  Total requests:   288,500
  Hits:             2,004
  Misses:           286,496
  Hit Ratio:        0.69%
  Time elapsed:     0.297s
```

## 请自行预处理一下样例，可用于测试

https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon
https://github.com/kvcache-ai/Mooncake/tree/main/FAST25-release/traces
