from datetime import datetime
import enum
from sqlalchemy import BigInteger, String, Text, Boolean, Numeric, ForeignKey, DateTime, Enum, Integer, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = 'pending_payment'
    PAID = 'paid'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'

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
    fixed_delivery_content: Mapped[str | None] = mapped_column(Text)
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
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT)
    payment_method: Mapped[str] = mapped_column(String(50), default="bank_transfer")
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

class PaymentConfig(Base):
    __tablename__ = "payment_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_name: Mapped[str | None] = mapped_column(String(255))
    account_no: Mapped[str | None] = mapped_column(String(255))
    account_name: Mapped[str | None] = mapped_column(String(255))
    vietqr_bank_code: Mapped[str | None] = mapped_column(String(20))
    webhook_secret: Mapped[str | None] = mapped_column(String(255))
    webhook_provider: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

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
