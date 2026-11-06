# Tiêu chí tính Severity — EthicalQuoc

> Tài liệu tham chiếu: severity (mức nghiêm trọng) của một finding được tính như thế nào.
> Mọi dòng đều trích từ code thật: [Analyze/ExploitabilityAnalysis.py](Analyze/ExploitabilityAnalysis.py) (tĩnh) và [main.py](main.py) (động).

---

## 1. Tổng quan — severity đi qua 2 giai đoạn

```
[Stage 4-5 TĨNH]  score (int)  --_calc_severity-->  severity ban đầu
                                                          |
[Stage 8 ĐỘNG]  replay thấy bằng chứng mạnh  --_escalate_severity-->  severity (chỉ NÂNG, không hạ)
```

- **Tĩnh** ([ExploitabilityAnalysis.py](Analyze/ExploitabilityAnalysis.py)): mỗi format có hàm `_analyze_*` chấm một **điểm số nguyên** dựa trên pattern/keyword trong giá trị. Điểm → severity qua một bảng ngưỡng cố định.
- **Động** ([main.py:28](main.py#L28) `_escalate_severity`): sau khi replay, nếu response lộ bằng chứng mạnh hơn thì **nâng** severity lên. Không bao giờ hạ.

> ⚠️ Severity ≠ `evidence`. `severity` = "nếu có thật thì nguy hiểm cỡ nào" (giả định xấu nhất). `evidence` (`static-only`/`dynamic-weak`/`dynamic-strong`) = "replay có thấy hành vi đổi không". Hai field độc lập. Mọi finding luôn ở mức **Suspected**, không bao giờ tự Confirmed.

---

## 2. Bảng ngưỡng điểm → severity (dùng chung mọi format)

[ExploitabilityAnalysis.py:36-43](Analyze/ExploitabilityAnalysis.py#L36) — `_calc_severity(score)`:

| Điểm (`score`) | Severity |
|---|---|
| `>= 9` | **Critical** |
| `6 – 8` | **High** |
| `3 – 5` | **Medium** |
| `< 3` | **Low** |

Và `exploitable = score >= ngưỡng` (ngưỡng tùy format, xem dưới).

---

## 3. Chấm điểm TĨNH theo từng format

### 3.1. PHP — [_analyze_php:136-221](Analyze/ExploitabilityAnalysis.py#L136)

Điểm nền = **1**. Cộng dồn theo nhánh đầu tiên khớp (ưu tiên từ trên xuống):

| Điều kiện | +điểm | exploit_type | probe |
|---|---|---|---|
| Có keyword gadget (`monolog`, `laravel`, `symfony`, `guzzle`, `phpggc`…) | **+6** | Gadget Chain | `gadget_chain` |
| Có magic method (`__wakeup`, `__destruct`, `__tostring`…) | **+4** | Magic Method Abuse | `magic_method` |
| Có field **privilege** (`admin`, `role`, `is_admin`, `level`…) | **+3** | Privilege Escalation | — |
|  → kèm field boolean `b:0/1;` | **+2 nữa** | …Boolean Flip | `flip_boolean` |
|  → kèm field integer `i:\d+;` | **+1 nữa** | …Integer Manipulation | `modify_integer` |
|  → kèm field string `s:\d+:"…"` | +0 | …String Manipulation | `modify_string` |
| Có field **identity** (`username`, `email`, `name`, `uid`…) | **+2** | Identity Spoofing | `modify_string` |
| Có field **sensitive** (`token`, `password`, `secret`, `key`…) | **+1** | Sensitive Field Manipulation | `modify_string` |

**FLOOR quan trọng** ([:207-218](Analyze/ExploitabilityAnalysis.py#L207)): nếu là **native PHP serialized** (khớp `O:\d+:"` / `C:\d+:"` / `a:\d+:\{`) thì `score = max(score, 6)` → **tối thiểu High** (lý do: `unserialize()` input người dùng = CWE-502, RCE-capable).

`exploitable = score >= 3`.

> 👉 Đây là lý do `ref_tag` (`O:3:"Tag":1:{…"name"…}`) ra **High**: chỉ match field identity (+2 → score 3), nhưng vì là native PHP `O:` nên bị **floor lên 6 = High**.

### 3.2. Java — [_analyze_java:267-334](Analyze/ExploitabilityAnalysis.py#L267)

Điểm nền = **2**.

| Điều kiện | +điểm | probe |
|---|---|---|
| Subtype = Jackson Polymorphic Typing (`["class",{…}]` / `@class`) | **+5** → return luôn | `jackson_manual` |
| Native Java object (magic bytes / `rO0AB` / `aced0005`) | **+4** | — |
| Gadget chain cụ thể (CommonsCollections, TemplatesImpl, Spring, Groovy, JNDI, Rome) | **+5 mỗi chain khớp** | `ysoserial` |
| URLDNS (`urldns`, `java.net.url`, `java.util.hashmap`) | **+3** | `urldns_probe` |
| Không khớp gadget nào | +0 (Unknown Gadget) | `urldns_probe` |

`exploitable = score >= 5`. (Native object +4 trên nền 2 = 6 → **High**; có gadget chain = 7+ → thường **Critical**.)

### 3.3. Python Pickle — [_analyze_pickle:336-374](Analyze/ExploitabilityAnalysis.py#L336)

| Điều kiện | score | exploit_type | probe |
|---|---|---|---|
| Subtype = jsonpickle Object Injection | **10** | jsonpickle Object Injection RCE | `jsonpickle_exec` |
| Pickle có pattern RCE rõ (`os.system`, `subprocess`, `exec`, `__reduce__`, `__import__`) | **10** | Python Pickle RCE | `pickle_exec` |
| Pickle không thấy pattern RCE trong text | **8** | Python Pickle RCE | `pickle_exec` |

→ Pickle luôn **Critical** (8–10). Lý do: `pickle.loads()` trên input không tin = RCE theo thiết kế, không cần gadget.

### 3.4. YAML — [_analyze_yaml:376-411](Analyze/ExploitabilityAnalysis.py#L376)

Điểm nền = 0, cộng dồn theo pattern:

| Pattern | +điểm |
|---|---|
| `!!python/object/apply:` | **+10** (YAML Python RCE) |
| `!!javax.script` | **+9** |
| `!!python/object:` | **+7** |
| `!!java.`/`!!javax.`/`!!com.sun` | **+7** |
| `!!python/module:` | **+6** |
| Có hàm nguy hiểm (`os.system`, `subprocess`, `exec`, `eval`, `__import__`) | **+3 nữa** |

`exploitable = score >= 5`. Không match tag nguy hiểm nào → `score 0`, severity Low, không flag.

### 3.5. Wrapper (PHP stream) — [_analyze_wrapper:427-456](Analyze/ExploitabilityAnalysis.py#L427)

Lấy điểm **cao nhất** trong các wrapper khớp (không cộng dồn):

| Wrapper | score | probe |
|---|---|---|
| `expect://` | **10** | `rce` |
| `phar://` | **8** | `phar_deser` |
| `gopher://` | 7 | `ssrf` |
| `php://input` | 7 | `php_input` |
| `data://` | 7 | `code_inject` |
| `file://` | 6 | `lfi` |
| `php://filter` | 5 | `lfi` |
| `glob://` | 4 | `traversal` |
| `zlib://`/`bzip2://`/`compress.zlib://` | 3 | `stream` |

`exploitable = score >= 5`.

### 3.6. .NET — [_analyze_dotnet:458-509](Analyze/ExploitabilityAnalysis.py#L458)

Điểm nền = **2**, cộng dồn:

| Điều kiện | +điểm | probe |
|---|---|---|
| ViewState (`/we[xyp]`) | **+7** | `viewstate` |
| JSON.NET `"$type"` | **+8** | `jsonnet` |
| BinaryFormatter | **+9** | `dotnet_deser` |
| ObjectStateFormatter / LosFormatter | **+8** | `dotnet_deser` |
| NetDataContractSerializer | **+7** | `dotnet_deser` |
| Không khớp signature cụ thể | +0 (Unknown Pattern) | `dotnet_deser` |

`exploitable = score >= 5`.

### 3.7. Node.js — [_analyze_nodejs:511-550](Analyze/ExploitabilityAnalysis.py#L511)

Điểm nền = **2**, cộng dồn:

| Điều kiện | +điểm | probe |
|---|---|---|
| `_$$nd_func$$_` (node-serialize) | **+10** | `node_serialize` |
| `__proto__` | **+5** | `proto_pollution` |
| `constructor` + `prototype` | **+4** | `proto_pollution` |
| Không khớp | +0 (Unknown Pattern) | `proto_pollution` |

`exploitable = score >= 5`.

### 3.8. Ruby — [_analyze_ruby:557-571](Analyze/ExploitabilityAnalysis.py#L557)

| Điều kiện | score |
|---|---|
| Marshal (đã xác nhận ở Fingerprint) | **3** (nền) |
| + keyword Rails/session (`activesupport`, `psych`, `rack::session`…) | **+4** → 7 |

`exploitable = score >= 3`. (Marshal cơ bản = Medium; có gadget Rails = High.)

### 3.9. Format không nhận diện được

[:27-28](Analyze/ExploitabilityAnalysis.py#L27): `score=0`, severity **Low**, `exploitable=False`.

---

## 4. Nâng severity ở giai đoạn ĐỘNG — [main.py:28-46](main.py#L28) `_escalate_severity`

Sau replay, soi `body_sample` + `indicators` của response mutated. **Chỉ nâng, không hạ**:

| Dấu hiệu trong response | Nâng lên | Lý do |
|---|---|---|
| Marker RCE (`functorexception`, `invokertransformer`, `java.lang.runtime`, `runtime' threw`) | **Critical** | gadget chain chạm tới `Runtime.exec` |
| Marker deser (`objectinputstream`, `invalidclassexception`, `streamcorruptedexception`) | **High** | `ObjectInputStream` đã xử lý byte attacker |
| `receivedtype` + indicator "content differs" | **High** | type bị deserialize đã đổi |

Chỉ nâng khi tier mới **cao hơn** severity tĩnh ([:44](main.py#L44)). Khi nâng, ghi `severity_note = "raised from X — <lý do>"`. Nếu `severity_note` rỗng trong report → severity đến **hoàn toàn từ tĩnh**, replay không đụng.

---

## 5. Tóm tắt 1 dòng

> **Severity = một con điểm số nguyên (cộng dồn theo keyword/pattern của format, có floor cho native object) ánh xạ qua ngưỡng 3/6/9 ra Low/Medium/High/Critical; rồi có thể được NÂNG (không hạ) nếu replay lộ marker RCE/deserialization trong response.**

Nó phản ánh **mức nguy hiểm giả định nếu lỗ hổng có thật**, không phải xác nhận lỗ hổng — xác nhận là việc của người review (tool luôn báo *Suspected*).
