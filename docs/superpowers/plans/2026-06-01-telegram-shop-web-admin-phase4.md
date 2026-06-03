# Telegram Shop Web Admin Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the web admin UI for better daily operation without changing core order, product, inventory, or security behavior.

**Architecture:** Keep FastAPI/Jinja/Tailwind CDN. Make targeted template improvements plus small route data additions. Do not introduce React, build steps, or database schema changes.

**Tech Stack:** FastAPI, Jinja2, Tailwind CDN, Chart.js, SQLAlchemy async.

---

## Files and responsibilities

- Modify `app/web/templates/base.html`: responsive shell, mobile sidebar, toast system, shared form loading state helpers.
- Modify `app/web/templates/orders.html`: inline bill modal, loading/disabled states, better empty state.
- Modify `app/web/templates/dashboard.html`: better visual stats, empty chart state, low-stock card.
- Modify `app/web/templates/products.html`: responsive table wrapper, better empty state, loading buttons.
- Modify `app/web/templates/inventory.html`: better empty state, loading button.
- Modify `app/web/main.py`: add low stock data to dashboard context.

## Scope

Included:
- Responsive sidebar for mobile/tablet.
- Toast notifications replacing top query-string `msg` blocks visually.
- Inline bill preview modal using existing bill route.
- Loading/disabled state for approve/reject and save/import forms.
- Better empty states.
- Preserve visual direction: Slate/Emerald, Inter, rounded-2xl, light glassmorphism, no violet/purple classes.

Not included:
- Frontend framework rewrite.
- New packages.
- Upload/storage for digital files.
- Database migrations.
- Commit unless user explicitly asks.

---

### Task 1: Responsive app shell and toast helpers

**Files:**
- Modify: `app/web/templates/base.html`

Steps:
- [ ] Change `<body>` layout so sidebar is hidden on small screens and main content can scroll.
- [ ] Add mobile top-bar menu button that toggles sidebar overlay.
- [ ] Add sidebar overlay backdrop.
- [ ] Add toast rendering when `msg` exists in template context.
- [ ] Add JS helpers:
  - `toggleSidebar()`
  - `closeSidebar()`
  - `setLoading(form, label)`
  - auto-hide toast after 5 seconds
- [ ] Keep all colors Slate/Emerald/Amber/Red only.

Verification:
- [ ] `python -m compileall app run.py`
- [ ] Inspect base template for no `purple` or `violet`.

### Task 2: Orders polish with inline bill modal and loading states

**Files:**
- Modify: `app/web/templates/orders.html`

Steps:
- [ ] Remove inline flash block because base toast handles `msg`.
- [ ] Add responsive wrappers for filter tabs and action forms.
- [ ] Replace bill link behavior with button opening modal containing `<img src="/admin/orders/{{ order.id }}/bill">`.
- [ ] Keep fallback text when no bill exists.
- [ ] Update approve/reject forms to call `setLoading(this, 'Đang xử lý...')` after confirm returns true.
- [ ] Improve empty state with clear action to reset filters.

Verification:
- [ ] Bill modal opens/closes from page JS.
- [ ] Approve/reject confirm still appears.
- [ ] CSRF hidden inputs remain.

### Task 3: Dashboard polish and low stock summary

**Files:**
- Modify: `app/web/main.py`
- Modify: `app/web/templates/dashboard.html`

Steps:
- [ ] In dashboard route, query active products and count unsold inventory per product.
- [ ] Build `low_stock_products` list for products with stock `< 5`, limit 6.
- [ ] Pass `low_stock_products` to dashboard template.
- [ ] Add dashboard card/list for low stock products.
- [ ] Improve chart empty state when all chart data is zero.
- [ ] Keep recent orders empty state.

Verification:
- [ ] `python -m compileall app/web/main.py`
- [ ] Dashboard renders with zero orders/products and with data.

### Task 4: Products and inventory polish

**Files:**
- Modify: `app/web/templates/products.html`
- Modify: `app/web/templates/inventory.html`

Steps:
- [ ] Remove inline flash blocks because base toast handles `msg`.
- [ ] Add `overflow-x-auto` around products table.
- [ ] Add loading state to add/edit/disable product forms.
- [ ] Add loading state to inventory import form.
- [ ] Improve empty states with clear next action.
- [ ] Keep all `csrf_token` hidden inputs.

Verification:
- [ ] Product add/edit/disable forms still include CSRF.
- [ ] Inventory add form still includes CSRF.
- [ ] No purple/violet classes.

### Task 5: Final verification

**Files:**
- All changed templates and `app/web/main.py`

Steps:
- [ ] Run `python -m compileall app run.py`.
- [ ] Search changed templates for `purple|violet`; expected none.
- [ ] Search POST forms for `csrf_token`; expected all admin forms protected.
- [ ] Read lints for `app/web/main.py`.
- [ ] Manually inspect key pages: dashboard, orders, products, inventory.

---

## Handoff notes

- Keep behavior same; Phase 4 is UI-only except low-stock data addition.
- Do not remove CSRF, audit, rate limit, or CSV export code from Phase 3.
- If responsive CSS conflicts with desktop layout, prefer desktop admin usability and keep mobile fallback simple.
