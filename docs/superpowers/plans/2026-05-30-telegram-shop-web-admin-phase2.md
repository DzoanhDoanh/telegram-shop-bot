# Telegram Shop Web Admin Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve admin workflow for a Telegram digital goods shop by adding category-aware product management, safer bulk inventory import, better order filtering, reject reasons, and approve/reject confirmations.

**Architecture:** Keep existing FastAPI/Jinja structure for Phase 2 and make targeted route/template changes in `app/web/main.py` plus existing templates. Do not add database migrations; use existing `Category`, `Product`, `InventoryItem`, and `Order` fields. Preserve Phase 1 delivery safety.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, Tailwind CDN, SQLAlchemy async, aiogram, PostgreSQL.

---

## Files and responsibilities

- Modify `app/web/main.py`: add category-aware product routes, edit/disable product routes, duplicate-safe inventory import, richer order filters, reject reason handling.
- Modify `app/web/templates/products.html`: add search/filter UI, category select, edit modal per row, disable form/button.
- Modify `app/web/templates/inventory.html`: show duplicate-safe import summary message and clearer digital goods wording.
- Modify `app/web/templates/orders.html`: add date/product filters, reject reason field, approve/reject confirmations.

## Phase 2 scope

Included:

- Product create with category select or new category fallback.
- Product edit: name, price, description, category.
- Product soft delete/disable by setting `Product.is_active = False`.
- Product search/filter by query and category.
- Inventory bulk import duplicate protection by `product_id + content`.
- Inventory import summary: added, duplicate, blank counts.
- Order filters by status, product, date range.
- Reject order with admin-provided reason sent to Telegram user.
- Browser confirm before approve/reject.

Not included:

- Database migrations or unique indexes.
- Native binary file upload/storage.
- CSRF/rate-limit/audit log/export CSV from Phase 3.
- React/Next rewrite.
- Commit unless user explicitly asks.

---

### Task 1: Category-aware product create/edit/disable routes

**Files:**
- Modify: `app/web/main.py`

- [ ] **Step 1: Update `products_page` signature and filters**

Replace `products_page` signature:

```python
async def products_page(request: Request, msg: str = ""):
```

with:

```python
async def products_page(request: Request, msg: str = "", q: str = "", category_id: int | None = None):
```

Inside `products_page`, replace current product query block with:

```python
        categories_result = await session.execute(
            select(Category).where(Category.is_active == True).order_by(Category.name.asc())
        )
        categories = categories_result.scalars().all()

        product_query = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.is_active == True)
            .order_by(Product.created_at.desc())
        )
        if q:
            product_query = product_query.where(Product.name.ilike(f"%{q}%"))
        if category_id:
            product_query = product_query.where(Product.category_id == category_id)

        result = await session.execute(product_query)
        raw_products = result.scalars().all()
```

Keep stock calculation loop, but include `categories`, `q`, and `category_id` in template context:

```python
        "categories": categories,
        "q": q,
        "category_id": category_id,
```

- [ ] **Step 2: Update add product route signature**

Replace `add_product_web` form parameters:

```python
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
```

with:

```python
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    category_id: int | None = Form(None),
    new_category: str = Form(""),
```

Replace default category block with:

```python
        cat = None
        if category_id:
            cat = await session.get(Category, category_id)
        if not cat and new_category.strip():
            cat = Category(name=new_category.strip(), emoji="📦")
            session.add(cat)
            await session.flush()
        if not cat:
            cat = await session.scalar(select(Category).where(Category.is_active == True).limit(1))
        if not cat:
            cat = Category(name="General", emoji="📦")
            session.add(cat)
            await session.flush()
```

Keep `Product(...)`, `session.add(product)`, `await session.commit()`.

- [ ] **Step 3: Add edit product route**

Add after `add_product_web`:

```python
@app.post("/admin/products/{product_id}/edit")
async def edit_product_web(
    product_id: int,
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    description: str = Form(""),
    category_id: int | None = Form(None),
    new_category: str = Form(""),
):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)

        cat = None
        if category_id:
            cat = await session.get(Category, category_id)
        if not cat and new_category.strip():
            cat = Category(name=new_category.strip(), emoji="📦")
            session.add(cat)
            await session.flush()
        if not cat:
            cat = product.category

        product.name = name.strip()
        product.price = price
        product.description = description.strip() or None
        product.category_id = cat.id
        await session.commit()

    return RedirectResponse(f"/admin/products?msg=Đã cập nhật sản phẩm '{name}'", status_code=302)
```

- [ ] **Step 4: Add soft delete route**

Add after edit route:

```python
@app.post("/admin/products/{product_id}/disable")
async def disable_product_web(product_id: int, request: Request):
    if not is_authenticated(request):
        return _redirect_login()

    async with async_session() as session:
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            return RedirectResponse("/admin/products?msg=Sản phẩm không tồn tại", status_code=302)
        product.is_active = False
        await session.commit()

    return RedirectResponse(f"/admin/products?msg=Đã ẩn sản phẩm #{product_id}", status_code=302)
```

- [ ] **Step 5: Compile**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: exit code `0`.

---

### Task 2: Product UI for search/category/edit/disable

**Files:**
- Modify: `app/web/templates/products.html`

- [ ] **Step 1: Add search/filter form below header row**

Insert after header row closing `</div>`:

```html
<form method="GET" action="/admin/products" class="mb-6 grid grid-cols-1 md:grid-cols-4 gap-3">
    <input name="q" value="{{ q }}" placeholder="Tìm sản phẩm..."
           class="md:col-span-2 px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition-colors">
    <select name="category_id"
            class="px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
        <option value="">Tất cả danh mục</option>
        {% for c in categories %}
        <option value="{{ c.id }}" {% if category_id == c.id %}selected{% endif %}>{{ c.name }}</option>
        {% endfor %}
    </select>
    <button class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-100 rounded-xl font-semibold transition-colors">Lọc</button>
</form>
```

- [ ] **Step 2: Update action column**

Replace current action cell content with:

```html
<div class="flex items-center justify-center gap-3">
    <a href="/admin/inventory?product_id={{ p.id }}" class="text-xs text-emerald-400 hover:underline font-medium">+ Nạp Kho</a>
    <button onclick="document.getElementById('editModal{{ p.id }}').classList.remove('hidden')" class="text-xs text-slate-300 hover:text-slate-100 font-medium">Sửa</button>
    <form method="POST" action="/admin/products/{{ p.id }}/disable" onsubmit="return confirm('Ẩn sản phẩm này khỏi shop?')" class="inline">
        <button type="submit" class="text-xs text-red-400 hover:text-red-300 font-medium">Ẩn</button>
    </form>
</div>
```

- [ ] **Step 3: Add edit modal per product**

Inside `{% for p in products %}` after each `</tr>`, add:

```html
<div id="editModal{{ p.id }}" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
    <div class="w-full max-w-lg bg-slate-900 border border-slate-700 rounded-2xl p-7 shadow-2xl">
        <div class="flex justify-between items-center mb-6">
            <h3 class="text-lg font-bold text-slate-100">Sửa Sản Phẩm</h3>
            <button onclick="document.getElementById('editModal{{ p.id }}').classList.add('hidden')" class="text-slate-400 hover:text-slate-100 transition-colors text-xl leading-none">&times;</button>
        </div>
        <form method="POST" action="/admin/products/{{ p.id }}/edit" class="space-y-4">
            <input name="name" required value="{{ p.name }}" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
            <input name="price" type="number" min="0" required value="{{ '%.0f'|format(p.price) }}" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
            <select name="category_id" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
                {% for c in categories %}
                <option value="{{ c.id }}" {% if p.category and p.category.id == c.id %}selected{% endif %}>{{ c.name }}</option>
                {% endfor %}
            </select>
            <input name="new_category" placeholder="Hoặc nhập danh mục mới" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition-colors">
            <textarea name="description" rows="3" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors resize-none">{{ p.description or '' }}</textarea>
            <div class="flex gap-3 pt-2">
                <button type="button" onclick="document.getElementById('editModal{{ p.id }}').classList.add('hidden')" class="flex-1 py-2.5 rounded-xl border border-slate-700 text-slate-400 hover:text-slate-100 hover:border-slate-600 font-medium transition-all text-sm">Hủy</button>
                <button type="submit" class="flex-1 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 active:scale-95 text-slate-900 font-bold transition-all text-sm">Lưu</button>
            </div>
        </form>
    </div>
</div>
```

- [ ] **Step 4: Add category fields to add product modal**

In add product form, after price field and before description, add:

```html
<div>
    <label class="block text-sm font-medium text-slate-300 mb-1.5">Danh Mục</label>
    <select name="category_id" class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
        <option value="">Tự động / danh mục mới</option>
        {% for c in categories %}
        <option value="{{ c.id }}">{{ c.name }}</option>
        {% endfor %}
    </select>
</div>
<div>
    <label class="block text-sm font-medium text-slate-300 mb-1.5">Danh Mục Mới <span class="text-slate-500 text-xs">(tùy chọn)</span></label>
    <input name="new_category" placeholder="Vd: Netflix, Game, Proxy"
           class="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-slate-100 placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition-colors">
</div>
```

- [ ] **Step 5: Compile template indirectly**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: exit code `0`.

---

### Task 3: Duplicate-safe inventory import

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/templates/inventory.html`

- [ ] **Step 1: Replace inventory import parsing**

In `add_inventory_web`, replace:

```python
    items = [k.strip() for k in keys.split("\n") if k.strip()]
    if not items:
        return RedirectResponse(f"/admin/inventory?msg=Không có key hợp lệ nào", status_code=302)
```

with:

```python
    raw_lines = [line.strip() for line in keys.splitlines()]
    blank_count = sum(1 for line in raw_lines if not line)
    items = []
    seen_in_request = set()
    request_duplicate_count = 0
    for line in raw_lines:
        if not line:
            continue
        if line in seen_in_request:
            request_duplicate_count += 1
            continue
        seen_in_request.add(line)
        items.append(line)

    if not items:
        return RedirectResponse("/admin/inventory?msg=Không có digital goods hợp lệ nào", status_code=302)
```

- [ ] **Step 2: Replace DB insert loop**

Inside session block after product check, replace current loop:

```python
        for key in items:
            session.add(InventoryItem(product_id=product_id, content=key))
        await session.commit()
```

with:

```python
        existing_result = await session.execute(
            select(InventoryItem.content).where(
                InventoryItem.product_id == product_id,
                InventoryItem.content.in_(items),
            )
        )
        existing = set(existing_result.scalars().all())
        new_items = [item for item in items if item not in existing]

        for item in new_items:
            session.add(InventoryItem(product_id=product_id, content=item))
        await session.commit()
```

- [ ] **Step 3: Replace success redirect**

Replace current success redirect with:

```python
    duplicate_count = request_duplicate_count + len(existing)
    return RedirectResponse(
        f"/admin/inventory?product_id={product_id}&msg=Đã nạp {len(new_items)} digital goods vào '{product.name}'. Bỏ qua {duplicate_count} trùng, {blank_count} dòng rỗng.",
        status_code=302,
    )
```

- [ ] **Step 4: Update inventory wording**

In `inventory.html`, replace label text `Danh Sách Key / Tài Khoản` with `Digital Goods (Key / Account / Link / File instructions)` and placeholder with:

```html
placeholder="account@example.com:password123&#10;KEY-XXXX-YYYY-ZZZZ&#10;https://example.com/download/file.zip&#10;File access: Drive link + password"
```

- [ ] **Step 5: Compile**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: exit code `0`.

---

### Task 4: Order filters and reject reason route

**Files:**
- Modify: `app/web/main.py`

- [ ] **Step 1: Update imports**

If not already imported, ensure `datetime` is already imported. `app/web/main.py` already has:

```python
from datetime import datetime, timedelta
```

- [ ] **Step 2: Update `orders_page` signature**

Replace:

```python
async def orders_page(request: Request, status: str = "all", msg: str = ""):
```

with:

```python
async def orders_page(
    request: Request,
    status: str = "all",
    msg: str = "",
    product_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
):
```

- [ ] **Step 3: Add product/date filters**

Inside session block, after status filter, add:

```python
        if product_id:
            q = q.where(Order.product_id == product_id)
        if date_from:
            start = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.where(Order.created_at >= start)
        if date_to:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.where(Order.created_at < end)

        products_result = await session.execute(
            select(Product).where(Product.is_active == True).order_by(Product.name.asc())
        )
        products = products_result.scalars().all()
```

Then include in template context:

```python
        "products": products,
        "product_id": product_id,
        "date_from": date_from,
        "date_to": date_to,
```

- [ ] **Step 4: Update reject route signature and message**

Replace reject route signature:

```python
async def reject_order_web(order_id: int, request: Request):
```

with:

```python
async def reject_order_web(order_id: int, request: Request, reason: str = Form("")):
```

Replace Telegram reject text with:

```python
                    text=(
                        f"❌ <b>Đơn hàng #{order_id} đã bị từ chối.</b>\n\n"
                        f"Lý do: {reason.strip() or 'Thanh toán chưa hợp lệ hoặc chưa xác minh được.'}\n\n"
                        "Vui lòng liên hệ hỗ trợ nếu bạn có thắc mắc."
                    )
```

- [ ] **Step 5: Compile**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: exit code `0`.

---

### Task 5: Orders UI filters, reject reason, confirmations

**Files:**
- Modify: `app/web/templates/orders.html`

- [ ] **Step 1: Add filter form below status tabs**

Insert after filter tabs block:

```html
<form method="GET" action="/admin/orders" class="mb-6 grid grid-cols-1 md:grid-cols-5 gap-3">
    <input type="hidden" name="status" value="{{ current_status }}">
    <select name="product_id" class="md:col-span-2 px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
        <option value="">Tất cả sản phẩm</option>
        {% for p in products %}
        <option value="{{ p.id }}" {% if product_id == p.id %}selected{% endif %}>{{ p.name }}</option>
        {% endfor %}
    </select>
    <input type="date" name="date_from" value="{{ date_from }}" class="px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
    <input type="date" name="date_to" value="{{ date_to }}" class="px-4 py-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-100 focus:outline-none focus:border-emerald-500 transition-colors">
    <button class="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-100 rounded-xl font-semibold transition-colors">Lọc</button>
</form>
```

- [ ] **Step 2: Add approve confirm**

Update approve form tag from:

```html
<form method="POST" action="/admin/orders/{{ order.id }}/approve" class="inline">
```

To:

```html
<form method="POST" action="/admin/orders/{{ order.id }}/approve" onsubmit="return confirm('Duyệt đơn #{{ order.id }} và gửi digital goods cho khách?')" class="inline">
```

- [ ] **Step 3: Add reject reason input and confirm**

Replace reject form block with:

```html
<form method="POST" action="/admin/orders/{{ order.id }}/reject" onsubmit="return confirm('Từ chối đơn #{{ order.id }}?')" class="inline-flex items-center gap-2">
    <input name="reason" placeholder="Lý do" class="w-32 px-2 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-600 text-xs focus:outline-none focus:border-red-500">
    <button type="submit" class="px-3 py-1.5 bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-bold rounded-xl hover:bg-red-500/20 transition-colors duration-150">
        ❌ Hủy
    </button>
</form>
```

- [ ] **Step 4: Compile**

Run:

```bash
python -m compileall app/web/main.py
```

Expected: exit code `0`.

---

### Task 6: Phase 2 verification

**Files:**
- Verify changed files from Tasks 1-5

- [ ] **Step 1: Compile all app code**

Run:

```bash
python -m compileall app run.py
```

Expected: exit code `0`.

- [ ] **Step 2: Lint changed files**

Read lints for:

```text
app/web/main.py
app/web/templates/products.html
app/web/templates/inventory.html
app/web/templates/orders.html
```

Expected: no new linter errors.

- [ ] **Step 3: Manual web smoke test**

With `python run.py` running, verify:

1. Login to `/login`.
2. Open `/admin/products`.
3. Add product with new category `Netflix`.
4. Edit product name/price/category.
5. Search product by part of name.
6. Filter product by category.
7. Disable product and verify it disappears from active list.
8. Open `/admin/inventory`, import duplicate lines and blank lines.
9. Verify message reports added/trùng/rỗng counts.
10. Open `/admin/orders`, filter by product/date/status.
11. Reject pending order with reason and verify Telegram message includes reason if bot is available.
12. Click approve and reject buttons and verify browser confirmation appears.

- [ ] **Step 4: Preserve Phase 1 safety check**

Search app code for:

```text
order_service.approve_order
```

Expected: no matches.

Search app code for:

```text
order.status = OrderStatus.COMPLETED
```

Expected: only in `app/services/delivery_service.py` after Telegram send success.

---

## Handoff notes

- Phase 2 intentionally avoids DB schema changes. Duplicate import is application-level protection, not a database unique constraint.
- Digital goods remain text rows in `InventoryItem.content`.
- Product disable is soft delete only; old orders still reference disabled products.
- If template layout becomes cramped, keep functionality first and polish in Phase 4.
