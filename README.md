# dtelegram

Script Python tự động kết nối reward account trên dTelecom thông qua một profile GenLogin đang chạy cục bộ.

## Mục đích

Project này dùng `requests` để gọi GenLogin API và dùng `playwright` để attach vào trình duyệt của profile GenLogin qua CDP. Sau khi kết nối thành công, script sẽ mở trang reward của dTelecom và tự động thực hiện một số bước connect tài khoản như Discord và X.

## Thành phần chính

- `genlogin_reward_connect.py`: script tự động hóa toàn bộ luồng kết nối reward.
- `Genlogin API.postman_collection.json`: bộ request Postman để tham khảo các API GenLogin.

## Yêu cầu

- Python 3.10+ khuyến nghị
- GenLogin chạy trên máy local
- Một profile GenLogin hợp lệ
- Có thể đăng nhập GenLogin bằng:
  - `GENLOGIN_TOKEN`, hoặc
  - `GENLOGIN_EMAIL` và `GENLOGIN_PASSWORD`

## Cài đặt

Tạo môi trường ảo:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Cài thư viện cần thiết:

```powershell
pip install requests playwright
playwright install
```

## Cấu hình

Script tự đọc file `.env` nằm cùng thư mục với `genlogin_reward_connect.py`.

Ví dụ `.env`:

```env
GENLOGIN_PROFILE_ID=your_profile_id
GENLOGIN_TOKEN=your_genlogin_token
# Hoac dung email/password thay cho token
# GENLOGIN_EMAIL=your_email@gmail.com
# GENLOGIN_PASSWORD=your_password
GENLOGIN_BASE_URL=http://localhost:55550
```

Các biến môi trường hỗ trợ:

- `GENLOGIN_PROFILE_ID`: ID của profile GenLogin cần start hoặc attach.
- `GENLOGIN_TOKEN`: Bearer token của GenLogin.
- `GENLOGIN_EMAIL`: email đăng nhập GenLogin nếu không dùng token.
- `GENLOGIN_PASSWORD`: mật khẩu GenLogin nếu không dùng token.
- `GENLOGIN_BASE_URL`: địa chỉ API local của GenLogin. Mặc định là `http://localhost:55550`.

## Cách chạy

Chạy bằng cấu hình từ `.env`:

```powershell
python genlogin_reward_connect.py
```

Hoặc truyền trực tiếp tham số:

```powershell
python genlogin_reward_connect.py --profile-id your_profile_id --token your_token
```

Các tham số CLI hiện có:

- `--profile-id`: profile ID của GenLogin
- `--token`: bearer token của GenLogin
- `--email`: email đăng nhập GenLogin
- `--password`: mật khẩu đăng nhập GenLogin
- `--base-url`: base URL của GenLogin API
- `--startup-timeout`: số giây chờ profile khởi động
- `--action-timeout`: số giây chờ selector hoặc popup
- `--screenshot-on-error`: đường dẫn file screenshot khi lỗi

Ví dụ đầy đủ:

```powershell
python genlogin_reward_connect.py `
  --profile-id your_profile_id `
  --base-url http://localhost:55550 `
  --action-timeout 30 `
  --startup-timeout 90
```

## Luồng hoạt động

Script thực hiện lần lượt các bước sau:

1. Đọc cấu hình từ `.env` và tham số dòng lệnh.
2. Xác thực với GenLogin bằng token hoặc email/password.
3. Lấy thông tin profile và tìm browser endpoint.
4. Nếu chưa có endpoint thì gọi API để start profile rồi poll danh sách profile đang chạy.
5. Attach Playwright vào browser của GenLogin qua CDP.
6. Mở trang `https://rewards.dtelecom.org/reward`.
7. Tự động chạy các bước reward hiện được cấu hình trong mã:
   - `Connect Discord`
   - `Connect X #5`
   - `Connect X #4`

## Lưu ý quan trọng

- Script đang dựa vào XPath và cấu trúc giao diện hiện tại của trang reward, Discord và X. Nếu UI thay đổi, script có thể cần cập nhật selector.
- Script giả định profile GenLogin đã sẵn sàng để dùng Playwright attach vào browser.
- Nếu xảy ra lỗi trong lúc chạy, script sẽ cố gắng chụp ảnh màn hình mặc định vào file `genlogin_reward_error.png`.
- File `.env` thường chứa thông tin nhạy cảm, không nên commit lên GitHub.

## Khắc phục lỗi cơ bản

- Nếu báo thiếu `profile ID`, hãy kiểm tra lại `GENLOGIN_PROFILE_ID` hoặc tham số `--profile-id`.
- Nếu báo thiếu xác thực, hãy cung cấp `GENLOGIN_TOKEN` hoặc đồng thời `GENLOGIN_EMAIL` và `GENLOGIN_PASSWORD`.
- Nếu không attach được vào browser, hãy kiểm tra GenLogin local API đang chạy đúng `GENLOGIN_BASE_URL`.
- Nếu không tìm thấy nút trên trang reward, khả năng cao giao diện đã thay đổi hoặc profile chưa đăng nhập đúng tài khoản cần thiết.

## Gợi ý sử dụng Postman collection

File `Genlogin API.postman_collection.json` có thể dùng để:

- test đăng nhập GenLogin
- lấy thông tin profile
- kiểm tra các endpoint local trước khi chạy automation

## Bảo mật

- Không đưa token, email, mật khẩu thật vào README.
- Nên giữ `.env` trong `.gitignore`.
