# Web Admin Professional Redesign Plan

## Goal

Làm lại Web Admin Panel trông chuyên nghiệp hơn, thao tác rõ hơn, giảm lỗi vận hành, nhưng không phá logic bot/web đã ổn: auth, CSRF, audit, order approval, delivery, inventory.

## Current Problems

### Visual/UI

- Giao diện dark mode có nền Slate/Emerald nhưng thiếu design system thống nhất.
- Nhiều button cùng kiểu nhưng ý nghĩa khác nhau, khó phân biệt hành động chính/phụ/nguy hiểm.
- Table dày thông tin, action nằm sát nhau, dễ bấm nhầm.
- Modal thêm/sửa sản phẩm dài và hơi “thô”.
- Toast đã có nhưng chưa thành hệ thống feedback hoàn chỉnh.
- Dashboard chưa giống trang điều hành shop thật, thiếu “việc cần làm hôm nay”.

### UX/Operation

- Admin chưa được dẫn luồng rõ: tạo sản phẩm → nạp kho → duyệt đơn → giao hàng.
- Trang orders chưa đủ rõ đơn nào cần xử lý ngay.
- Approve/reject là thao tác quan trọng nhưng chưa có panel xác nhận chuyên nghiệp.
- Inventory import chưa có preview/validation trước khi nhập.
- Product management thiếu trạng thái rõ: active, low stock, out of stock.
- Empty states có nhưng chưa đủ hướng dẫn bước tiếp theo.

### Code/Template

- `app/web/main.py` quá lớn, nhiều route + export + auth + business glue trong một file.
- Templates lặp class Tailwind nhiều.
- Chưa có component/macro chung cho cards, buttons, badges, empty states, page header.
- Inline JS rải rác trong templates.

## Design Direction

Giữ stack hiện tại:

- FastAPI
- Jinja2
- Tailwind CDN
- Chart.js
- SQLAlchemy async

Không chuyển sang React/Next lúc này. Admin server-rendered vẫn phù hợp dự án nhỏ, deploy đơn giản.

Visual style:

- Professional dark admin dashboard.
- Slate/Emerald primary.
- Amber for warning/pending.
- Red for destructive/error.
- No purple/violet.
- Less emoji in core navigation; use icons sparingly.
- More spacing, clearer hierarchy.
- Consistent cards, badges, buttons, form fields.

## Recommended Implementation Phases

### Phase A — Design System + Layout Foundation

Goal: tạo nền UI chuyên nghiệp trước khi sửa từng page.

Files:

- `app/web/templates/base.html`
- Create `app/web/templates/components/ui.html`
- Create `app/web/static/admin.css` if static serving is added, or keep inline CSS in base for now.

Scope:

- Create reusable Jinja macros:
  - `page_header(title, subtitle, actions)`
  - `stat_card(label, value, hint, tone)`
  - `badge(text, tone)`
  - `button(label, href/action, tone)`
  - `empty_state(title, body, action)`
  - `confirm_panel(...)` if needed
- Redesign base shell:
  - cleaner sidebar
  - grouped nav sections: Overview, Operations, Data
  - top bar with shop status, quick actions
  - consistent toast area
- Define button styles:
  - Primary: emerald
  - Secondary: slate
  - Warning: amber
  - Danger: red
- Standardize table shell:
  - sticky header
  - consistent padding
  - hover states
  - clear empty state

Verification:

- All pages still render.
- No CSRF removal.
- No purple/violet.

### Phase B — Dashboard as Operations Center

Goal: dashboard phải cho admin biết hôm nay cần làm gì.

Files:

- `app/web/main.py`
- `app/web/templates/dashboard.html`

Scope:

- Add “Action Required” section:
  - pending payment count
  - low stock count
  - out of stock count
  - failed/old pending orders if derivable
- Add quick actions:
  - Review pending orders
  - Add product
  - Import inventory
  - Export CSV
- Improve stat cards:
  - revenue
  - completed orders
  - pending orders
  - active products
  - low stock
- Improve recent orders list with clearer status badges.
- Keep revenue chart but make empty state clean.

Verification:

- Dashboard works with empty DB.
- Dashboard works with sample data.

### Phase C — Orders Page Redesign

Goal: duyệt đơn rõ, an toàn, ít bấm nhầm.

Files:

- `app/web/templates/orders.html`
- `app/web/main.py` if extra counts/filter context needed

Scope:

- Replace current dense table with professional order management view:
  - top summary chips: All, Pending, Completed, Cancelled
  - filter bar clearly separated
  - row layout shows priority info first: order id, product, customer, amount, status, proof, action
- Pending orders should visually stand out.
- Approve action:
  - opens confirmation panel/modal
  - explains: “Duyệt sẽ gửi digital goods cho khách”
  - loading state
- Reject action:
  - requires reason or uses clear default
  - confirmation modal
- Bill modal:
  - larger, centered, better fallback if image fails
- Add row-level status badges with consistent tone.

Verification:

- POST forms keep CSRF.
- Approve/reject still call existing safe delivery/reject logic.
- Bill modal works.

### Phase D — Products Page Redesign

Goal: quản lý catalog dễ hơn và giảm lỗi khi tạo/sửa sản phẩm.

Files:

- `app/web/templates/products.html`
- `app/web/main.py` if product counts needed

Scope:

- Product page as catalog manager:
  - header with add product CTA
  - filter/search card
  - product table/card hybrid
- Product row should show:
  - name
  - category
  - price
  - stock badge
  - active status
  - actions grouped: edit, stock, disable
- Add/edit product modal clearer:
  - split sections: Basic info, Category, Pricing, Description
  - helper text for digital goods
  - validation hints
- Disable action uses danger confirmation modal, not browser confirm.

Verification:

- Add product still supports existing/new category.
- Product announcement to Telegram still works.
- Edit/disable keep CSRF.

### Phase E — Inventory Page Redesign

Goal: nạp digital goods ít lỗi hơn.

Files:

- `app/web/templates/inventory.html`
- `app/web/main.py` if preview route added later

Scope:

- Make inventory import flow explicit:
  1. Select product
  2. Paste goods
  3. Review import summary
  4. Submit
- For MVP without new route, improve current UI:
  - examples for key/account/link/file instruction
  - clear duplicate handling explanation
  - show selected product stock
  - low/out stock badges in stock overview
- Future optional: preview before import.

Verification:

- Bulk import still skips duplicate.
- Success/error toast clear.

### Phase F — Template Refactor and Stability

Goal: giảm lỗi lâu dài.

Files:

- Split `app/web/main.py` later into:
  - `app/web/routes/dashboard.py`
  - `app/web/routes/orders.py`
  - `app/web/routes/products.py`
  - `app/web/routes/inventory.py`
  - `app/web/routes/exports.py`
- Keep this phase after UI is stable.

Scope:

- Move route groups gradually.
- Keep existing URLs unchanged.
- Add shared dependencies/helpers:
  - auth guard
  - template context
  - CSRF check
  - redirect helper

Verification:

- All routes same URL.
- Compile + manual smoke test.

## Recommended First Slice

Do **Phase A + B first**.

Reason:

- Most visible improvement fastest.
- Creates reusable macros/classes for later pages.
- Dashboard becomes professional operations center.
- Low risk to order/payment logic.

Then do:

1. Phase C — Orders page, because money flow depends on it.
2. Phase D — Products page.
3. Phase E — Inventory page.
4. Phase F — route/template refactor.

## Risks

- Too much redesign at once can break working admin flows.
- Browser confirm/modal JS can break if not tested carefully.
- Refactoring `main.py` too early may introduce route regressions.

Mitigation:

- Keep URLs and POST endpoints unchanged.
- Keep CSRF hidden inputs in every POST form.
- Implement page by page.
- Verify after each page:
  - `python -m compileall app run.py`
  - no linter errors
  - login
  - product add/edit/disable
  - inventory import
  - order approve/reject

## Definition of Done

- Admin looks like a real operations dashboard.
- Main actions are clear and hard to misuse.
- Every empty/error/success state tells admin what to do next.
- Pending orders and low stock are obvious.
- Forms have labels, helper text, and clear primary actions.
- No web security regression: CSRF, session, audit, rate limit remain.
