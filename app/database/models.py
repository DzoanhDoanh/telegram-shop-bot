from datetime import datetime
import enum
from sqlalchemy import BigInteger, String, Text, Boolean, Numeric, ForeignKey, DateTime, Enum, Integer, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def string_enum(enum_cls: type[enum.Enum], **kwargs):
    return Enum(
        enum_cls,
        values_callable=lambda values: [item.value for item in values],
        **kwargs,
    )


class Base(DeclarativeBase):
    pass

class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = 'pending_payment'
    PAID = 'paid'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'

class VoucherDiscountType(str, enum.Enum):
    PERCENT = 'percent'
    AMOUNT = 'amount'

class WalletTxType(str, enum.Enum):
    DEPOSIT = 'deposit'
    PURCHASE = 'purchase'
    REFUND = 'refund'
    ADMIN_CREDIT = 'admin_credit'
    ADMIN_DEBIT = 'admin_debit'

class WalletTxStatus(str, enum.Enum):
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    UNDERPAID = 'underpaid'
    REVIEW_REQUIRED = 'review_required'
    UNMATCHED = 'unmatched'
    LATE_PAID = 'late_paid'

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    crm_tag: Mapped[str | None] = mapped_column(String(100))
    internal_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_spent: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    wallet_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    wallet_transactions: Mapped[list["WalletTransaction"]] = relationship(back_populates="user")

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    emoji: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[list["Product"]] = relationship(back_populates="category")

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    delivery_mode: Mapped[str] = mapped_column(String(30), default="inventory")
    payment_mode: Mapped[str] = mapped_column(String(30), default="wallet_only")
    fixed_delivery_content: Mapped[str | None] = mapped_column(Text)
    is_bundle: Mapped[bool] = mapped_column(Boolean, default=False)
    bundle_items_text: Mapped[str | None] = mapped_column(Text)
    allow_quantity_selection: Mapped[bool] = mapped_column(Boolean, default=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    max_quantity: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    category: Mapped["Category"] = relationship(back_populates="products")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="product")
    orders: Mapped[list["Order"]] = relationship(back_populates="product")

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    original_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    voucher_code: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    payment_method: Mapped[str] = mapped_column(String(50), default="bank_transfer")
    bank_transfer_reference_normalized: Mapped[str | None] = mapped_column(String(100), index=True)
    payment_proof: Mapped[str | None] = mapped_column(String(255))
    payment_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    inventory_items: Mapped[list["InventoryItem"]] = relationship(back_populates="order")

class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_sold: Mapped[bool] = mapped_column(Boolean, default=False)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))

    product: Mapped["Product"] = relationship(back_populates="inventory_items")
    order: Mapped["Order"] = relationship(back_populates="inventory_items")

class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    discount_type: Mapped[VoucherDiscountType] = mapped_column(Enum(VoucherDiscountType), default=VoucherDiscountType.AMOUNT)
    discount_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    min_order_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    max_discount_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    applies_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    applies_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PaymentConfig(Base):
    __tablename__ = "payment_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str | None] = mapped_column(String(255))
    account_no: Mapped[str | None] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    vietqr_bank_code: Mapped[str | None] = mapped_column(String(20))
    webhook_secret: Mapped[str | None] = mapped_column(String(255))
    webhook_provider: Mapped[str | None] = mapped_column(String(50))
    min_deposit_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    min_deposit_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class AppConfig(Base):
    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_display_name: Mapped[str | None] = mapped_column(String(255))
    support_username: Mapped[str | None] = mapped_column(String(255))
    welcome_text: Mapped[str | None] = mapped_column(Text)
    help_text: Mapped[str | None] = mapped_column(Text)
    terms_text: Mapped[str | None] = mapped_column(Text)
    support_text: Mapped[str | None] = mapped_column(Text)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_product_search: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_support_forwarding: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_lucky_spin: Mapped[bool] = mapped_column(Boolean, default=True)
    show_terms_button: Mapped[bool] = mapped_column(Boolean, default=True)
    show_help_button: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class BroadcastCampaignStatus(str, enum.Enum):
    DRAFT = 'draft'
    SENT = 'sent'
    PARTIAL = 'partial'
    FAILED = 'failed'

class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(Text)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[BroadcastCampaignStatus] = mapped_column(Enum(BroadcastCampaignStatus), default=BroadcastCampaignStatus.DRAFT, index=True)
    admin_actor: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)

class LuckySpinResultType(str, enum.Enum):
    WALLET_CREDIT = 'wallet_credit'
    VOUCHER = 'voucher'
    TEXT = 'text'

class LuckySpinLog(Base):
    __tablename__ = "lucky_spin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reward_label: Mapped[str] = mapped_column(String(255))
    result_type: Mapped[LuckySpinResultType] = mapped_column(Enum(LuckySpinResultType), index=True)
    reward_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    voucher_code: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class SupportTicketStatus(str, enum.Enum):
    OPEN = 'open'
    ADMIN_REPLIED = 'admin_replied'
    CLOSED = 'closed'

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[SupportTicketStatus] = mapped_column(string_enum(SupportTicketStatus), default=SupportTicketStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_admin_reply_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship()
    messages: Mapped[list["SupportMessage"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")

class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), index=True)
    sender_role: Mapped[str] = mapped_column(String(20))
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_actor: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ticket: Mapped["SupportTicket"] = relationship(back_populates="messages")

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tx_type: Mapped[WalletTxType] = mapped_column(Enum(WalletTxType))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[WalletTxStatus] = mapped_column(Enum(WalletTxStatus), default=WalletTxStatus.PENDING)
    reference: Mapped[str | None] = mapped_column(String(100), index=True)
    provider: Mapped[str | None] = mapped_column(String(50))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    deposit_message_id: Mapped[int | None] = mapped_column(BigInteger)
    deposit_qr_message_id: Mapped[int | None] = mapped_column(BigInteger)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_tx_id: Mapped[str | None] = mapped_column(String(255), index=True)
    normalized_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    admin_actor: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="wallet_transactions")
