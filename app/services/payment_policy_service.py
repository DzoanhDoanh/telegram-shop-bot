from __future__ import annotations

from dataclasses import dataclass

from app.database.models import Product
from app.services import wallet_service

PAYMENT_MODE_WALLET_ONLY = "wallet_only"
PAYMENT_MODE_DIRECT_BANK_ONLY = "direct_bank_only"
PAYMENT_MODE_WALLET_OR_DIRECT_BANK = "wallet_or_direct_bank"

PAYMENT_METHOD_WALLET = "wallet"
PAYMENT_METHOD_DIRECT_BANK = "direct_bank"

VALID_PAYMENT_MODES = {
    PAYMENT_MODE_WALLET_ONLY,
    PAYMENT_MODE_DIRECT_BANK_ONLY,
    PAYMENT_MODE_WALLET_OR_DIRECT_BANK,
}


@dataclass(slots=True)
class PaymentPolicyView:
    mode: str
    allowed_methods: tuple[str, ...]
    default_method: str
    mode_label: str
    checkout_hint: str


def normalize_payment_mode(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in VALID_PAYMENT_MODES:
        return raw
    return PAYMENT_MODE_WALLET_ONLY


def allowed_payment_methods(product: Product) -> tuple[str, ...]:
    mode = normalize_payment_mode(getattr(product, "payment_mode", None))
    if mode == PAYMENT_MODE_DIRECT_BANK_ONLY:
        return (PAYMENT_METHOD_DIRECT_BANK,)
    if mode == PAYMENT_MODE_WALLET_OR_DIRECT_BANK:
        return (PAYMENT_METHOD_WALLET, PAYMENT_METHOD_DIRECT_BANK)
    return (PAYMENT_METHOD_WALLET,)


def default_payment_method(product: Product) -> str:
    methods = allowed_payment_methods(product)
    return methods[0]


def is_payment_method_allowed(product: Product, payment_method: str | None) -> bool:
    clean_method = (payment_method or "").strip().lower()
    return clean_method in allowed_payment_methods(product)


def get_policy_view(product: Product) -> PaymentPolicyView:
    mode = normalize_payment_mode(getattr(product, "payment_mode", None))
    methods = allowed_payment_methods(product)
    if mode == PAYMENT_MODE_DIRECT_BANK_ONLY:
        return PaymentPolicyView(
            mode=mode,
            allowed_methods=methods,
            default_method=PAYMENT_METHOD_DIRECT_BANK,
            mode_label="Chỉ chuyển khoản trực tiếp",
            checkout_hint="Sản phẩm này không thanh toán qua ví. Bot sẽ tạo mã đơn và hướng dẫn chuyển khoản trực tiếp.",
        )
    if mode == PAYMENT_MODE_WALLET_OR_DIRECT_BANK:
        return PaymentPolicyView(
            mode=mode,
            allowed_methods=methods,
            default_method=PAYMENT_METHOD_WALLET,
            mode_label="Ví hoặc chuyển khoản trực tiếp",
            checkout_hint="Sản phẩm này cho phép trả bằng ví hoặc chuyển khoản trực tiếp theo mã đơn.",
        )
    return PaymentPolicyView(
        mode=PAYMENT_MODE_WALLET_ONLY,
        allowed_methods=methods,
        default_method=PAYMENT_METHOD_WALLET,
        mode_label="Chỉ thanh toán bằng ví",
        checkout_hint="Sản phẩm này chỉ thanh toán bằng số dư trong ví.",
    )


def get_payment_method_label(payment_method: str | None) -> str:
    clean_method = (payment_method or "").strip().lower()
    if clean_method == PAYMENT_METHOD_DIRECT_BANK:
        return "Chuyển khoản trực tiếp"
    if clean_method == PAYMENT_METHOD_WALLET:
        return "Ví"
    if clean_method == "bank_transfer":
        return "Chuyển khoản ngân hàng"
    return clean_method or "Chưa rõ"


def build_direct_bank_reference(order_code: str | None) -> str:
    return wallet_service.normalize_reference_text(order_code or "")
