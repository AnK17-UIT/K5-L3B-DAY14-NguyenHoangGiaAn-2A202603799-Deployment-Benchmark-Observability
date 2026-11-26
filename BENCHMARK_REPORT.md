# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Nguyen Hoang Gia An (K5-L3B · 2A202603799)
**Ngày chạy:** 2026-11-26
**Môi trường:** WSL2 Ubuntu trên Windows, Python 3.12 (`develop/.venv`), Docker 29.8.0

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Khớp ngưỡng mặc định `--slo-p95-ms 500` của `load_test.py` và bảo đảm 95% người dùng nhận phản hồi dưới nửa giây cho mock agent (latency nền 120–180 ms + retrieval ~20 ms). |
| Error rate `/ask` | `< 2.0 %` | Khớp ngưỡng mặc định `--slo-error-rate 0.02` (cho phép error budget 2% để chịu nhiễu `MOCK_ERROR_RATE=0.01` từ LLM upstream). |
| Accuracy trên golden dataset | `≥ 80 %` (sau sửa KB: `100 %`) | Bảo đảm chất lượng tối thiểu trước khi deploy (`--min-accuracy 0.8` ở baseline, nâng lên `--min-accuracy 1.0` không regression cho bản đã bổ sung KB). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, cổng `8002`, 300 request/mức, `MOCK_SLOW_RATE=0.03`)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.33 | 186.3 | 216.7 | 1685.5 | 1.00% | PASS |
| 10 | 37.81 | 191.1 | 223.3 | 1703.8 | 0.33% | PASS |
| 50 | 105.19 | 192.9 | 262.5 | 1716.7 | 0.67% | PASS |
| 100 | 70.07 | 314.6 | 2626.0 | 2772.0 | 1.00% | **FAIL** (p95 > 500 ms) |

*(Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.)*

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Không tăng tuyến tính.** Từ `c=1` (`4.33 req/s`) lên `c=10` (`37.81 req/s`) tăng ~8.7× (gần tuyến tính vì I/O async còn dư tài nguyên), lên `c=50` tăng còn ~2.78× (`105.19 req/s`), và tới `c=100` thì **RPS tụt xuống `70.07 req/s`** trong khi `p95` nhảy vọt lên **`2626.0 ms` (vi phạm SLO `≤ 500 ms`)**.
- Nguyên nhân: agent chỉ chạy **1 tiến trình Uvicorn đơn**; khi 100 kết nối đồng thời đổ vào, hàng đợi socket/event loop và lượng request chậm (`MOCK_SLOW_RATE=0.03` cộng thêm ~1500 ms) gây nghẽn hàng đợi (queuing delay), khiến cả `p50` (`314.6 ms`) lẫn `p95`/`p99` tăng vọt và throughput bão hoà rồi suy giảm.

### 2.2 Tail latency (agent v2, cổng `8002`, 300 request, concurrency `20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | SLO (p95 ≤ 500 ms) |
|---|---|---|---|---|
| 0 | 188.3 | 218.6 | 223.6 | PASS |
| 0.03 (mặc định) | 228.5 | 220.1 | 1691.1 | PASS |
| 0.1 | 356.8 | 1692.9 | 1708.8 | **FAIL** |

*(Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.)*

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **`p99` và `p95` nhạy nhất với request chậm:** khi chỉ 3% request chậm (`MOCK_SLOW_RATE=0.03`), `avg` chỉ tăng nhẹ từ `188.3 ms` lên `228.5 ms` và `p95` gần như đứng yên (`220.1 ms`), nhưng `p99` lập tức tăng hơn 7.5× lên `1691.1 ms`. Khi tăng lên 10% (`MOCK_SLOW_RATE=0.1`), `p95` cũng nổ vọt lên **`1692.9 ms` (vi phạm SLO)** trong khi `avg` mới là `356.8 ms` (trông vẫn "đạt" nếu đặt ngưỡng 500 ms theo trung bình).
- Vì vậy không được đặt SLO theo `average`: giá trị trung bình bị làm mượt bởi 90–97% request nhanh và **che giấu hoàn toàn tail latency**, khiến hàng trăm người dùng phải chờ gần 1.7 giây mà báo cáo trung bình vẫn xanh.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Ghi chú môi trường: cổng `8001` trên máy đang bị dịch vụ khác chiếm dụng nên agent `v1` được chạy trên cổng `8003`, còn agent `v2` chạy đúng cổng `8002`. Golden dataset nguyên bản 23 câu.)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.30% (21/23) | 100.00% (23/23) |
| Avg tokens / câu | 57.0 | 108.8 | 114.9 |
| Tổng cost (USD) | 0.000403 | 0.000758 | 0.000801 |
| Cost / câu đúng (USD) | 0.00040335 | 0.00003607 | 0.00003485 |
| Latency p50 / p95 (ms) | 165.6 / 185.9 | 190.8 / 218.0 | 181.9 / 204.5 |
| Quality gate | **FAIL** (`< 80%`) | **PASS** (`≥ 80%`, 0 regression) | **PASS** (`≥ 100%`, 0 regression) |

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.)*

**Những câu v2 trả lời sai ban đầu và cách bạn sửa (`develop/utils/mock_llm.py` → `KNOWLEDGE_BASE`):**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["jwt", "api key", "xác thực"]` giải thích JWT là token có chữ ký số và thời gian hết hạn (`exp`), khác với API key tĩnh. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["hpa", "kubernetes", "horizontal pod autoscaler"]` giải thích HPA scale pod theo CPU, memory và custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- `v2` thêm bước retrieval (~20 ms) và chèn context vào prompt nên `avg_tokens` gần gấp đôi (`57.0` → `108.8` / `114.9`), tổng chi phí tăng gần gấp đôi (`$0.000403` → `$0.000801`), và latency p95 tăng nhẹ (~20–32 ms).
- Tuy nhiên accuracy nhảy từ **4.35% (1/23)** lên **91.30% (21/23)** rồi **100% (23/23)**, làm **cost / câu đúng giảm hơn 11.5 lần** (từ `$0.00040335` xuống `$0.00003485`). Do đó `cost / câu đúng` phản ánh đúng hiệu quả kinh tế hơn nhiều so với `cost / câu`.

**Cách dùng exit code của `eval/run_eval.py` để chặn merge trong CI/CD:**

- `eval/run_eval.py` (dòng 198–211) kiểm tra `gate_ok = report["accuracy"] >= args.min_accuracy and not regressions` và thoát bằng `SystemExit(0 if gate_ok else 1)`.
- Trong pipeline CI (ví dụ GitHub Actions chạy trên Pull Request), thêm job khởi động agent v2 rồi chạy:
  ```bash
  python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json
  ```
- Nếu thay đổi prompt/KB làm accuracy tụt dưới ngưỡng hoặc gây bất kỳ regression nào so với baseline, lệnh trả **exit code `1`** → job CI chuyển trạng thái **failed** → bật *Branch Protection / Required Status Check* trên nhánh `main` sẽ tự động **chặn merge PR** trước khi code lọt lên production.

---

## 4. Observability stack (production, project `k5-day14-observability`)

*(Ghi chú kỹ thuật: `production/Dockerfile` mẫu thiếu `ENV PYTHONUSERBASE=/home/agent/.local` khiến container `agent` không tìm thấy `uvicorn` với user non-root `agent`; đã bổ sung 1 dòng này để stack hoạt động.)*

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png` (trace `941451678a70f9e202cd534cbc4d9924`, span `chat mock-llm-small`, `exception.type=utils.mock_llm.LLMError`, `Upstream LLM error: 503 Service Unavailable (mock)`)
- [x] Trang Alerts của Prometheus với **4 alert cùng đang `firing`**: `screenshots/prometheus-alert-firing.png` (`AgentInstanceDown`, `AgentHighErrorRate`, `AgentHighLatencyP95`, `LLMCostBurnRateHigh`)

### 4.2 Thí nghiệm "phá hệ thống"

Đã kích hoạt đồng thời `MOCK_ERROR_RATE=0.2`, `MOCK_SLOW_RATE=0.3`, `LLM_MODEL=mock-llm-large` lúc `t+0s` trên 3 agent, thực hiện `docker pause k5-day14-observability-agent-3` lúc `t+11s`, chạy tải Locust 30 users và đo thời gian chuyển trạng thái `firing` qua Prometheus API (`/api/v1/alerts`) & trang Alerts:

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, giá trị `20.2% > 5%`) | **76 giây** (pending từ `t+15s`, firing ở `t+76s`) | Error Rate (%) & HTTP Status 5xx |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, giá trị `1.91s > 1s`) | **~139 giây** (pending từ `t+19s`, firing sau `for: 2m`) | Latency p50/p95/p99 |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, giá trị `$11.79/giờ > $2/giờ`) | **~176 giây** (pending từ `t+56s`, firing sau `for: 2m`) | LLM Cost Burn Rate ($/h) & Tokens/sec |
| D | `docker pause` `agent-3` (lúc `t+11s`) | `AgentInstanceDown` (`for: 30s`, `up == 0`) | **45 giây** sau khi pause (`t+56s` từ `t+0s`, pending ở `t+28s`) | Up Instances / Target Health |
| E | `AGENT_VERSION=v1` | Không có alert nào firing | Không kích hoạt (HTTP 200, latency thấp hơn, cost rẻ hơn) | Chỉ thấy `agent_info{version="v1"}` đổi nhãn và avg tokens giảm |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

- Alert hạ tầng (4 Golden Signals) chỉ đo hệ thống có **nhanh và không lỗi HTTP** hay không, không biết câu trả lời có **đúng** hay không (`v1` thậm chí nhanh và rẻ hơn `v2` nhưng accuracy tụt từ 100% xuống 4.35%).
- Để phát hiện trong production cần: (1) **CI/CD Quality Gate** chạy `eval/run_eval.py` trên golden dataset trước mọi lần deploy và chặn merge khi exit code `1`; (2) **Online eval / LLM-as-a-judge** chấm mẫu ngẫu nhiên (vd 1–5% traffic thật) và xuất metric `agent_eval_accuracy` để đặt alert; (3) theo dõi **tín hiệu gián tiếp** như tỉ lệ RAG retrieval (`retrieved=true`), độ dài output/tokens đột ngột giảm, hoặc phản hồi thumbs-down của người dùng.

### 4.3 Debug bằng trace

Chọn 1 trace chậm tiêu biểu từ bài chạy tải 100 users (`screenshots/jaeger-slow-trace.png`):

- `trace_id`: `b99c8be28c21fe786a446de879488701`
- Tổng thời gian: **1779.0 ms** (root span `POST /ask`: `1779.012 ms`; wrapper `agent.run`: `1777.175 ms`; HTTP log: `1778.6 ms`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1686.1 ms**, **94.8%** tổng thời gian; so với `agent.retrieve_context` chỉ **90.9 ms** / 5.1%)
- Dòng log tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-26T09:15:28.444547+00:00", "level": "INFO", "service": "observable-agent", "instance": "83de125026ac", "event": "llm_call", "trace_id": "b99c8be28c21fe786a446de879488701", "span_id": "636890aaccb69946", "request_id": "2ff4dfe2fa0f", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1685.5}
{"ts": "2026-11-26T09:15:28.444880+00:00", "level": "INFO", "service": "observable-agent", "instance": "83de125026ac", "event": "http_request", "trace_id": "b99c8be28c21fe786a446de879488701", "span_id": "636890aaccb69946", "request_id": "2ff4dfe2fa0f", "method": "POST", "route": "/ask", "status": 200, "ms": 1778.6}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, spawn 10/s, 2 phút)

*(Số liệu lấy trực tiếp từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, dòng `Aggregated` và `POST /ask`.)*

| Số instance | Scope | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|---|
| 1 | Aggregated (`POST /ask` + `GET /health`) | 65.70 | 190 | 240 | 1700 | 68 / 7824 (0.87%) |
| 1 | `POST /ask` | 59.83 | 190 | 250 | 1700 | 68 / 7125 (0.95%) |
| 3 | Aggregated (`POST /ask` + `GET /health`) | 65.65 | 190 | 220 | 1700 | 68 / 7821 (0.87%) |
| 3 | `POST /ask` | 59.78 | 190 | 220 | 1700 | 68 / 7122 (0.95%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **Có cải thiện nhẹ p95:** khi scale từ 1 lên 3 agent, `p95` giảm từ **240 ms → 220 ms** (Aggregated) và **250 ms → 220 ms** (`POST /ask`); riêng `GET /health` giảm hơn một nửa từ **12 ms → 5 ms** do tải CPU/event-loop được chia đều trên 3 container.
- **Tuy nhiên RPS giữ nguyên (~65.7 req/s) và p99 vẫn là 1700 ms** vì nút thắt lúc này **không nằm ở CPU của agent**, mà nằm ở: (1) tốc độ sinh tải của 100 user Locust có `wait_time` giữa các request nên tổng cầu bị chặn quanh ~65 req/s; và (2) **latency I/O của bước gọi LLM upstream** (`chat mock-llm-small` chiếm ~95% thời gian request, trong đó `MOCK_SLOW_RATE=0.03` cộng thêm 1500 ms). Scale thêm replica agent chỉ giúp giảm hàng đợi nội bộ và tăng khả năng chịu tải lớn hơn, không rút ngắn được thời gian phản hồi của nhà cung cấp LLM.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Đo bằng percentile (`p95`/`p99`), không đo bằng trung bình:** ở `MOCK_SLOW_RATE=0.1`, `avg` chỉ `356.8 ms` nhưng `p95` đã lên `1692.9 ms` và vi phạm SLO.
  2. **Ba trụ cột Observability bổ trợ nhau:** Prometheus/Grafana phát hiện triệu chứng toàn cục (Golden Signals + alert), Jaeger chỉ ra chính xác span gây chậm (`chat mock-llm-small` chiếm 94.8%) hoặc `exception` khi lỗi, còn log JSON mang `trace_id` giúp đối chiếu chi tiết từng request.
  3. **Hạ tầng khỏe không đồng nghĩa AI trả lời đúng:** cần kết hợp eval trên golden dataset + quality gate (exit code CI) để chặn regression chất lượng và dùng `cost / câu đúng` khi đánh giá phiên bản agent.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - Thêm metric & alert cho **RAG retrieval hit-rate / empty-context rate**, **online eval quality score** (chấm mẫu tự động), **rate-limit (`429`) và budget-exhausted (`402`) rate**, **Redis latency / connection errors** (`/ready` 503), và **token-per-request anomaly** để phát hiện prompt injection hoặc vòng lặp tool-calling sớm.
