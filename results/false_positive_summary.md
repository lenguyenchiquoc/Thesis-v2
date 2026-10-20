# False-Positive Summary — EthicalQuoc

Tổng hợp từ các report trong `results/` (tính đến 2026-10-20). Mỗi report chạy đầy đủ
pipeline Stage 1–8 (có replay). Nguồn: extension capture → `POST /scan`.

## 1. Negative control — site thật, lành (KHÔNG có lỗ hổng deserialization)

Trên các site này, **mọi finding đều là false positive** (vì không tồn tại lỗ hổng thật).
Chỉ số quan trọng nhất: `likely_vulnerable` — tức số ca tool báo "nghi dính" sau khi replay.

| Target | Vectors quét | Findings (FP) | FP rate | likely_vulnerable | Unknown | Java | Ruby |
|---|---:|---:|---:|---:|---:|---:|---:|
| youtube.com | 11720 | 1200 | 10.2% | **0** | 1081 | 117 | 2 |
| youtube.com | 3468 | 375 | 10.8% | **0** | 333 | 39 | 3 |
| facebook.com | 925 | 143 | 15.5% | **0** | 142 | 0 | 1 |
| **Tổng** | **16113** | **1718** | **~10.7%** | **0** | 1556 | 156 | 6 |

**Kết luận chính:**
- **0 false "vulnerable"** trên toàn bộ traffic lành — tầng replay/oracle không xác nhận nhầm ca nào.
  Đây là bằng chứng mạnh cho precision của khâu xác nhận động.
- Tầng **detection** (static signature) over-flag ~10–15%, chủ yếu là `Unknown` (token base64/hex/protobuf
  bị nhận nhầm là "giống serialized"). Đây là false positive ở mức *phát hiện*, không phải mức *kết luận*.
- Nhóm `Java` trên YouTube là các header dạng `X-YouTube-Device` (token protobuf base64) bị nhận nhầm type.

**Nguồn nhiễu:** luật base64/hex lỏng trong `Utility/signatures.py` (các check "trông giống base64 dài ≥20"
mà không decode-để-kiểm-magic). Siết lại (decode rồi mới check magic bytes) dự kiến giảm mạnh cột `Unknown`
mà không ảnh hưởng `likely_vulnerable` (vốn đã 0).

## 2. Positive control — test env localhost Web_vul_env (CÓ lỗ hổng đã biết)

Trên test env, findings là **expected true positive**, không phải FP. Dùng để đối chứng recall.

| Report | Vectors | Findings | likely_vulnerable | Unknown | Java |
|---|---:|---:|---:|---:|---:|
| 2026-10-19T07-44 | 85 | 5 | 4 | 1 | 4 |
| 2026-10-19T07-52 | 83 | 7 | 6 | 1 | 6 |
| 2026-10-19T07-59 | 76 | 6 | 5 | 1 | 5 |

Các sink thật (`/api/integration/receive`, `/api/webhook/config`, `/api/theme/import`) đều bị gắn
`likely_vulnerable: true` — 0 false negative trên các endpoint vuln đã biết.

## 3. Đọc tổng hợp cho luận văn

| Phép đo | Benign (3 site) | Test env (localhost) |
|---|---|---|
| false "vulnerable" (FP sau replay) | **0** | — |
| false negative trên sink thật | — | **0** |
| over-flag ở tầng detection | ~10.7% (chủ yếu Unknown) | thấp (1 Unknown/report) |

Câu chuyện: **static detection ồn (mặc định "thà nghi còn hơn bỏ sót"), nhưng dynamic replay
confirmation kéo false-vulnerable về 0** — nhất quán triết lý "chỉ Suspected, không auto-Confirm".

> Lưu ý phương pháp: các lần quét benign ở trên chạy với replay BẬT (payload được gửi tới site thật).
> Lần đo FP sau nên dùng detection-only để không phát sinh traffic ra server bên thứ ba.
> result1.json / result2.json KHÔNG đưa vào bảng này (schema CLI khác — dump mutation, không phải findings).

## 4. Trước/sau khi siết signature (2026-10-20, detection-only)

Siết `looks_like_serialized()` — các luật base64/hex đổi sang decode-rồi-check-magic, bỏ 2 heuristic
thuần hình dạng. Đo trên cùng HAR (`do_replay=False`, không gửi mạng).

| HAR | vectors | findings trước | findings sau | typed thật (giữ) |
|---|---:|---:|---:|---|
| youtube.com | 7389 | 1425 (FP 19.3%) | **15** (FP 0.2%) | — (site lành) |
| comprehensive (đủ format) | 9767 | 145 | 74 | **48 → 48** (0 mất) |
| localhost Web_vul_env (thật) | 168 | 21 | 21 | **20 → 20** (0 mất) |

- **False positive YouTube giảm ~99%** (1425 → 15), chủ yếu cột `Unknown` (token base64/protobuf).
- **0 false negative**: toàn bộ detection thật ở test env (localhost 20) và synthetic đủ format
  (comprehensive 48) được giữ nguyên — đã verify từng type.
- Bắt được 1 regression suýt mất (double-base64 PHP) nhờ đối chứng comprehensive.har, đã vá.
- 116/116 unit test pass.
