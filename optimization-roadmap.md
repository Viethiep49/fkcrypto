# Optimization & Development Roadmap (FKCrypto)

## Overview
Kế hoạch phát triển và tối ưu hóa hệ thống FKCrypto theo 3 giai đoạn: Tối ưu hoá (Ngắn hạn), Nâng cấp Trí tuệ (Trung hạn) và Tự động hóa chiến lược (Dài hạn). Trọng tâm đầu tiên là cải thiện hiệu năng xử lý tính toán kỹ thuật phục vụ backtesting.

## Project Type
BACKEND (Python, Data Processing, AI Agents)

## Success Criteria
- Hệ thống tính toán chỉ báo kỹ thuật xử lý hàng triệu nến trong vài giây thay vì vài phút/giờ (thông qua `pandas` / `numpy`).
- Dữ liệu OHLCV được cache trên Redis để tránh rate limit của sàn giao dịch.
- Hệ thống `RiskGuardian` và `Kill Switch` được kiểm thử tự động với các kịch bản flash crash.
- Mở rộng `AlphaSeeker` và `NewsSentiment` để phân tích dữ liệu on-chain và ứng dụng RAG.

## Tech Stack
- **Data Processing:** `pandas`, `pandas-ta` / `numpy`
- **Cache:** `Redis`
- **AI/ML:** `LiteLLM`, Vector DB (cho RAG)
- **Testing:** `pytest`, Mocking

## File Structure
```text
fkcrypto/
├── src/
│   ├── agents/
│   │   ├── analyst.py         # Refactor to use pandas-ta
│   │   ├── sentiment.py       # Add RAG capabilities
│   │   ├── alpha_seeker.py    # Add On-chain data sources
│   ├── data/
│   │   ├── cache.py           # New Redis caching layer
│   │   ├── onchain.py         # New on-chain data source
```

## Task Breakdown

### Phase 1: Tối ưu hoá & Đóng gói (Optimization - Ngắn hạn)

**Task 1.1: Refactor Technical Analyst Agent**
- **Agent:** `backend-specialist`
- **Skill:** `python-patterns`, `clean-code`
- **Dependencies:** Không có
- **INPUT:** `src/agents/analyst.py` đang dùng vòng lặp `for` chậm chạp.
- **OUTPUT:** `analyst.py` sử dụng `pandas` và `pandas-ta` để tính toán chỉ báo bằng Vectorized Operations.
- **VERIFY:** Chạy `pytest tests/agents/test_analyst.py` thành công và đo lường thời gian thực thi nhanh hơn ít nhất 10x.

**Task 1.2: Implement Market Data Cache (Redis)**
- **Agent:** `backend-specialist`
- **Skill:** `database-design`
- **Dependencies:** Không có
- **INPUT:** `src/data/ccxt_source.py`
- **OUTPUT:** Lớp caching sử dụng Redis cho dữ liệu OHLCV.
- **VERIFY:** Gửi 2 request giống nhau liên tiếp, request thứ 2 không gọi API CCXT mà lấy trực tiếp từ Redis trong < 10ms.

**Task 1.3: Flash Crash & Kill Switch Simulation Tests**
- **Agent:** `test-engineer`
- **Skill:** `testing-patterns`
- **Dependencies:** Không có
- **INPUT:** `tests/risk/`
- **OUTPUT:** Bộ test CI/CD giả lập giá rớt 20% trong 1 phút.
- **VERIFY:** `pytest` xác nhận Kill Switch được trigger thành công dưới 1 giây và chặn toàn bộ các lệnh tiếp theo.

---

### Phase 2: Nâng cấp Trí tuệ Hệ thống (Intelligence - Trung hạn)

**Task 2.1: Xây dựng hệ thống RAG cho NewsSentiment Agent**
- **Agent:** `backend-specialist`
- **Skill:** `api-patterns`
- **Dependencies:** Không có
- **INPUT:** `src/agents/sentiment.py`
- **OUTPUT:** Tích hợp Vector DB lưu trữ tin tức lịch sử. Khi có tin mới, truy vấn các sự kiện tương tự làm context cho LLM.
- **VERIFY:** Prompt gửi cho LLM (thông qua LiteLLM) có chứa context lịch sử ("Sự kiện tương tự năm ngoái đã làm giá giảm 10%...").

**Task 2.2: Tích hợp On-chain Data cho AlphaSeeker**
- **Agent:** `backend-specialist`
- **Skill:** `api-patterns`
- **Dependencies:** Không có
- **INPUT:** `src/agents/alpha_seeker.py`
- **OUTPUT:** Data connector mới cho dữ liệu On-chain (ví dụ: dòng tiền rút/nạp ròng từ sàn).
- **VERIFY:** AlphaSeeker sinh ra được `Signal` hợp lệ dựa trên On-chain metrics.

---

### Phase 3: Tự động hóa chiến lược (MLOps - Dài hạn)

**Task 3.1: Walk-forward Optimization Engine**
- **Agent:** `backend-specialist`
- **Skill:** `architecture`
- **Dependencies:** Task 1.1 (Cần hệ thống backtest cực nhanh)
- **INPUT:** `src/backtesting/engine.py`
- **OUTPUT:** Script tự động chạy backtest hàng tuần và đề xuất bộ tham số YAML mới tối ưu hơn.
- **VERIFY:** Hệ thống tự sinh ra file YAML mới (bản draft) với thông số mang lại Profit Factor hoặc Sharpe Ratio cao hơn cấu hình cũ.

---

## Phase X: Verification
- [ ] Đảm bảo code tuân thủ tiêu chuẩn `ruff` (linter) và `mypy` (type checker).
- [ ] Chạy `python .agent/scripts/checklist.py .` thành công không có lỗi nghiêm trọng.
- [ ] Bộ Unit Tests cho tất cả module mới (Cache, RAG, Onchain) đạt coverage > 80%.
- [ ] Socratic Gate được tôn trọng.
