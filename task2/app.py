import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from passlib.context import CryptContext

try:
    from generated import openapi_models as api
except ImportError:
    script_path = os.path.join(os.path.dirname(__file__), "scripts", "generate_openapi_code.sh")
    subprocess.run([script_path], check=True)
    from generated import openapi_models as api


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/marketplace")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "20"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
ORDER_LIMIT_MINUTES = int(os.getenv("ORDER_LIMIT_MINUTES", "5"))


class OperationType(str, Enum):
    CREATE_ORDER = "CREATE_ORDER"
    UPDATE_ORDER = "UPDATE_ORDER"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    seller_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    seller_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    current_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    promo_code_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("promo_codes.id"), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_at_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")


class UserOperation(Base):
    __tablename__ = "user_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
PASSWORD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class ApiError(Exception):
    def __init__(self, error_code: str, message: str, status_code: int, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details


app = FastAPI(title="Marketplace API", version="1.0.0")
logger = logging.getLogger("marketplace")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
logger.addHandler(handler)


def api_error(error_code: str, message: str, status_code: int, details: dict[str, Any] | None = None) -> JSONResponse:
    payload = api.ErrorResponse(error_code=error_code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.middleware("http")
async def request_logger(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    request.state.request_id = request_id

    body_payload: dict[str, Any] | None = None
    if request.method in {"POST", "PUT", "DELETE"}:
        body = await request.body()
        if body:
            try:
                parsed = json.loads(body.decode())
                body_payload = mask_sensitive_data(parsed)
            except json.JSONDecodeError:
                body_payload = {"raw": "<non-json-body>"}

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive)

    started = datetime.now(timezone.utc)
    response = await call_next(request)

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    response.headers["X-Request-Id"] = request_id

    log_line = {
        "request_id": request_id,
        "method": request.method,
        "endpoint": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "user_id": getattr(request.state, "user_id", None),
        "timestamp": started.isoformat(),
    }
    if body_payload is not None:
        log_line["request_body"] = body_payload
    logger.info(json.dumps(log_line, ensure_ascii=True))
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return api_error(exc.error_code, exc.message, exc.status_code, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    details = {"violations": [{"field": ".".join(map(str, err["loc"])), "message": err["msg"]} for err in exc.errors()]}
    return api_error("VALIDATION_ERROR", "Validation failed", 400, details)


def mask_sensitive_data(data: Any) -> Any:
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if key.lower() in {"password", "pass", "secret"}:
                sanitized[key] = "***"
            else:
                sanitized[key] = mask_sensitive_data(value)
        return sanitized
    if isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return PASSWORD_CONTEXT.verify(plain, hashed)


def create_token(user: User, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + (timedelta(minutes=ACCESS_TOKEN_MINUTES) if token_type == "access" else timedelta(days=REFRESH_TOKEN_DAYS))
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        code = "TOKEN_EXPIRED" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, "Token expired", 401) from exc
    except jwt.InvalidTokenError as exc:
        code = "TOKEN_INVALID" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, "Token invalid", 401) from exc

    if payload.get("type") != expected_type:
        code = "TOKEN_INVALID" if expected_type == "access" else "REFRESH_TOKEN_INVALID"
        raise ApiError(code, "Wrong token type", 401)
    return payload


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError("TOKEN_INVALID", "Missing bearer token", 401)
    token = auth.removeprefix("Bearer ").strip()
    payload = decode_token(token, "access")

    user = db.get(User, payload["sub"])
    if not user:
        raise ApiError("TOKEN_INVALID", "User not found", 401)
    request.state.user_id = user.id
    return user


def require_roles(*roles: api.UserRole):
    def dependency(user: User = Depends(get_current_user)):
        allowed = {role.value for role in roles}
        if user.role not in allowed:
            raise ApiError("ACCESS_DENIED", "Access denied", 403)
        return user

    return dependency


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def to_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


def aware_dt(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ensure_user_owns_order_or_admin(order: Order, user: User):
    if user.role == api.UserRole.ADMIN.value:
        return
    if user.role != api.UserRole.USER.value:
        raise ApiError("ACCESS_DENIED", "Access denied", 403)
    if order.user_id != user.id:
        raise ApiError("ORDER_OWNERSHIP_VIOLATION", "Order belongs to another user", 403)


def to_product_response(product: Product) -> api.ProductResponse:
    return api.ProductResponse(
        id=UUID(product.id),
        name=product.name,
        description=product.description,
        price=round_money(product.price),
        stock=product.stock,
        category=product.category,
        status=api.ProductStatus(product.status),
        seller_id=UUID(product.seller_id),
        created_at=aware_dt(product.created_at),
        updated_at=aware_dt(product.updated_at),
    )


def to_order_response(order: Order) -> api.OrderResponse:
    return api.OrderResponse(
        id=UUID(order.id),
        user_id=UUID(order.user_id),
        status=api.OrderStatus(order.status),
        promo_code_id=to_uuid(order.promo_code_id),
        total_amount=round_money(order.total_amount),
        discount_amount=round_money(order.discount_amount),
        created_at=aware_dt(order.created_at),
        updated_at=aware_dt(order.updated_at),
        items=[
            api.OrderItemResponse(
                id=UUID(item.id),
                product_id=UUID(item.product_id),
                quantity=item.quantity,
                price_at_order=round_money(item.price_at_order),
            )
            for item in order.items
        ],
    )


def to_promo_response(promo: PromoCode) -> api.PromoCodeResponse:
    return api.PromoCodeResponse(
        id=UUID(promo.id),
        seller_id=UUID(promo.seller_id),
        code=promo.code,
        discount_type=api.DiscountType(promo.discount_type),
        discount_value=round_money(promo.discount_value),
        min_order_amount=round_money(promo.min_order_amount),
        max_uses=promo.max_uses,
        current_uses=promo.current_uses,
        valid_from=aware_dt(promo.valid_from),
        valid_until=aware_dt(promo.valid_until),
        active=promo.active,
    )


def check_order_rate_limit(db: Session, user_id: str, operation_type: OperationType):
    last_op = db.scalar(
        select(UserOperation)
        .where(UserOperation.user_id == user_id, UserOperation.operation_type == operation_type.value)
        .order_by(UserOperation.created_at.desc())
        .limit(1)
    )
    if last_op:
        last_ts = last_op.created_at if last_op.created_at.tzinfo else last_op.created_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_ts < timedelta(minutes=ORDER_LIMIT_MINUTES):
            raise ApiError("ORDER_LIMIT_EXCEEDED", "Too many operations", 429)


def validate_and_apply_promo(db: Session, promo_code_str: str | None, subtotal: Decimal) -> tuple[PromoCode | None, Decimal, Decimal]:
    discount = Decimal("0.00")
    total = subtotal
    promo: PromoCode | None = None

    if promo_code_str:
        promo = db.scalar(select(PromoCode).where(PromoCode.code == promo_code_str))
        now = datetime.now(timezone.utc)
        if not promo:
            raise ApiError("PROMO_CODE_INVALID", "Promo code invalid", 422)

        valid_from = promo.valid_from if promo.valid_from.tzinfo else promo.valid_from.replace(tzinfo=timezone.utc)
        valid_until = promo.valid_until if promo.valid_until.tzinfo else promo.valid_until.replace(tzinfo=timezone.utc)
        if not promo.active or promo.current_uses >= promo.max_uses or now < valid_from or now > valid_until:
            raise ApiError("PROMO_CODE_INVALID", "Promo code invalid", 422)

        if subtotal < promo.min_order_amount:
            raise ApiError("PROMO_CODE_MIN_AMOUNT", "Order total is below promo minimum", 422)

        if promo.discount_type == api.DiscountType.PERCENTAGE.value:
            discount = min(subtotal * promo.discount_value / Decimal("100"), subtotal * Decimal("0.70"))
        else:
            discount = min(promo.discount_value, subtotal)

        discount = round_money(discount)
        total = round_money(subtotal - discount)
        promo.current_uses += 1
    return promo, discount, total


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=api.AuthTokensResponse, status_code=201)
def register(payload: api.RegisterRequest, db: Session = Depends(get_db)):
    user = User(email=str(payload.email), password_hash=hash_password(payload.password), role=payload.role.value)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError("VALIDATION_ERROR", "Email already registered", 400, {"email": "already exists"}) from exc
    db.refresh(user)
    return api.AuthTokensResponse(
        access_token=create_token(user, "access"),
        refresh_token=create_token(user, "refresh"),
        token_type=api.TokenType.bearer,
    )


@app.post("/auth/login", response_model=api.AuthTokensResponse)
def login(payload: api.LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email)))
    if not user or not verify_password(payload.password, user.password_hash):
        raise ApiError("TOKEN_INVALID", "Invalid credentials", 401)
    return api.AuthTokensResponse(
        access_token=create_token(user, "access"),
        refresh_token=create_token(user, "refresh"),
        token_type=api.TokenType.bearer,
    )


@app.post("/auth/refresh", response_model=api.AuthTokensResponse)
def refresh(payload: api.RefreshRequest, db: Session = Depends(get_db)):
    claims = decode_token(payload.refresh_token, "refresh")
    user = db.get(User, claims["sub"])
    if not user:
        raise ApiError("REFRESH_TOKEN_INVALID", "Refresh token invalid", 401)
    return api.AuthTokensResponse(
        access_token=create_token(user, "access"),
        refresh_token=create_token(user, "refresh"),
        token_type=api.TokenType.bearer,
    )


@app.get("/products", response_model=api.ProductPageResponse)
def list_products(
    page: int = Query(default=0, ge=0),
    size: int = Query(default=20, ge=1, le=100),
    status: api.ProductStatus | None = Query(default=None),
    category: str | None = Query(default=None, min_length=1, max_length=100),
    user: User = Depends(require_roles(api.UserRole.USER, api.UserRole.SELLER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    query = select(Product)
    count_query = select(func.count(Product.id))
    if status:
        query = query.where(Product.status == status.value)
        count_query = count_query.where(Product.status == status.value)
    if category:
        query = query.where(Product.category == category)
        count_query = count_query.where(Product.category == category)

    total = db.scalar(count_query) or 0
    products = db.scalars(query.order_by(Product.created_at.desc()).offset(page * size).limit(size)).all()
    return api.ProductPageResponse(items=[to_product_response(p) for p in products], totalElements=total, page=page, size=size)


@app.get("/products/{product_id}", response_model=api.ProductResponse)
def get_product(product_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    product = db.get(Product, str(product_id))
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404)
    return to_product_response(product)


def ensure_product_ownership(user: User, product: Product):
    if user.role == api.UserRole.ADMIN.value:
        return
    if user.role != api.UserRole.SELLER.value:
        raise ApiError("ACCESS_DENIED", "Access denied", 403)
    if product.seller_id != user.id:
        raise ApiError("ACCESS_DENIED", "Seller can modify only own products", 403)


@app.post("/products", response_model=api.ProductResponse, status_code=201)
def create_product(
    payload: api.ProductCreate,
    user: User = Depends(require_roles(api.UserRole.SELLER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    product = Product(
        name=payload.name,
        description=payload.description,
        price=round_money(payload.price),
        stock=payload.stock,
        category=payload.category,
        status=payload.status.value,
        seller_id=user.id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return to_product_response(product)


@app.put("/products/{product_id}", response_model=api.ProductResponse)
def update_product(
    product_id: UUID,
    payload: api.ProductUpdate,
    user: User = Depends(require_roles(api.UserRole.SELLER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    product = db.get(Product, str(product_id))
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404)
    ensure_product_ownership(user, product)

    product.name = payload.name
    product.description = payload.description
    product.price = round_money(payload.price)
    product.stock = payload.stock
    product.category = payload.category
    product.status = payload.status.value
    db.commit()
    db.refresh(product)
    return to_product_response(product)


@app.delete("/products/{product_id}", response_model=api.ProductResponse)
def delete_product(
    product_id: UUID,
    user: User = Depends(require_roles(api.UserRole.SELLER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    product = db.get(Product, str(product_id))
    if not product:
        raise ApiError("PRODUCT_NOT_FOUND", "Product not found", 404)
    ensure_product_ownership(user, product)

    product.status = api.ProductStatus.ARCHIVED.value
    db.commit()
    db.refresh(product)
    return to_product_response(product)


@app.post("/promo-codes", response_model=api.PromoCodeResponse, status_code=201)
def create_promo_code(
    payload: api.PromoCodeCreateRequest,
    user: User = Depends(require_roles(api.UserRole.SELLER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    if payload.valid_until <= payload.valid_from:
        raise ApiError("VALIDATION_ERROR", "valid_until must be after valid_from", 400)

    promo = PromoCode(
        seller_id=user.id,
        code=payload.code,
        discount_type=payload.discount_type.value,
        discount_value=round_money(payload.discount_value),
        min_order_amount=round_money(payload.min_order_amount),
        max_uses=payload.max_uses,
        current_uses=0,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        active=True,
    )
    db.add(promo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError("VALIDATION_ERROR", "Promo code already exists", 400) from exc
    db.refresh(promo)
    return to_promo_response(promo)


@app.post("/orders", response_model=api.OrderResponse, status_code=201)
def create_order(
    payload: api.OrderCreateRequest,
    user: User = Depends(require_roles(api.UserRole.USER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    check_order_rate_limit(db, user.id, OperationType.CREATE_ORDER)

    active_order = db.scalar(
        select(Order).where(
            Order.user_id == user.id,
            Order.status.in_([api.OrderStatus.CREATED.value, api.OrderStatus.PAYMENT_PENDING.value]),
        )
    )
    if active_order:
        raise ApiError("ORDER_HAS_ACTIVE", "User already has active order", 409)

    product_ids = [str(item.product_id) for item in payload.items]
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids))).all()}

    shortage: list[dict[str, Any]] = []
    for item in payload.items:
        product = products.get(str(item.product_id))
        if not product:
            raise ApiError("PRODUCT_NOT_FOUND", f"Product {item.product_id} not found", 404)
        if product.status != api.ProductStatus.ACTIVE.value:
            raise ApiError("PRODUCT_INACTIVE", f"Product {item.product_id} inactive", 409)
        if product.stock < item.quantity:
            shortage.append({"product_id": product.id, "requested": item.quantity, "available": product.stock})

    if shortage:
        raise ApiError("INSUFFICIENT_STOCK", "Insufficient stock", 409, {"items": shortage})

    subtotal = Decimal("0.00")
    order = Order(
        user_id=user.id,
        status=api.OrderStatus.CREATED.value,
        total_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
    )
    db.add(order)
    db.flush()

    for item in payload.items:
        product = products[str(item.product_id)]
        product.stock -= item.quantity
        snapshot = round_money(product.price)
        subtotal += snapshot * item.quantity
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item.quantity,
                price_at_order=snapshot,
            )
        )

    subtotal = round_money(subtotal)
    promo, discount, total = validate_and_apply_promo(db, payload.promo_code, subtotal)
    order.promo_code_id = promo.id if promo else None
    order.discount_amount = discount
    order.total_amount = total

    db.add(UserOperation(user_id=user.id, operation_type=OperationType.CREATE_ORDER.value))
    db.commit()
    db.refresh(order)
    return to_order_response(order)


@app.get("/orders/{order_id}", response_model=api.OrderResponse)
def get_order(
    order_id: UUID,
    user: User = Depends(require_roles(api.UserRole.USER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    order = db.get(Order, str(order_id))
    if not order:
        raise ApiError("ORDER_NOT_FOUND", "Order not found", 404)
    ensure_user_owns_order_or_admin(order, user)
    return to_order_response(order)


@app.put("/orders/{order_id}", response_model=api.OrderResponse)
def update_order(
    order_id: UUID,
    payload: api.OrderUpdateRequest,
    user: User = Depends(require_roles(api.UserRole.USER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    order = db.get(Order, str(order_id))
    if not order:
        raise ApiError("ORDER_NOT_FOUND", "Order not found", 404)
    ensure_user_owns_order_or_admin(order, user)

    if order.status != api.OrderStatus.CREATED.value:
        raise ApiError("INVALID_STATE_TRANSITION", "Order can be updated only in CREATED", 409)

    check_order_rate_limit(db, order.user_id, OperationType.UPDATE_ORDER)

    for item in order.items:
        product = db.get(Product, item.product_id)
        if product:
            product.stock += item.quantity

    order.items.clear()
    db.flush()

    product_ids = [str(item.product_id) for item in payload.items]
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids))).all()}
    shortage: list[dict[str, Any]] = []

    for item in payload.items:
        product = products.get(str(item.product_id))
        if not product:
            raise ApiError("PRODUCT_NOT_FOUND", f"Product {item.product_id} not found", 404)
        if product.status != api.ProductStatus.ACTIVE.value:
            raise ApiError("PRODUCT_INACTIVE", f"Product {item.product_id} inactive", 409)
        if product.stock < item.quantity:
            shortage.append({"product_id": product.id, "requested": item.quantity, "available": product.stock})

    if shortage:
        raise ApiError("INSUFFICIENT_STOCK", "Insufficient stock", 409, {"items": shortage})

    subtotal = Decimal("0.00")
    for item in payload.items:
        product = products[str(item.product_id)]
        product.stock -= item.quantity
        snapshot = round_money(product.price)
        subtotal += snapshot * item.quantity
        db.add(
            OrderItem(order_id=order.id, product_id=product.id, quantity=item.quantity, price_at_order=snapshot)
        )
    subtotal = round_money(subtotal)

    discount = Decimal("0.00")
    total = subtotal
    if order.promo_code_id:
        promo = db.get(PromoCode, order.promo_code_id)
        now = datetime.now(timezone.utc)
        if not promo:
            raise ApiError("PROMO_CODE_INVALID", "Promo code invalid for recalculation", 422)

        valid_from = promo.valid_from if promo.valid_from.tzinfo else promo.valid_from.replace(tzinfo=timezone.utc)
        valid_until = promo.valid_until if promo.valid_until.tzinfo else promo.valid_until.replace(tzinfo=timezone.utc)
        promo_valid = promo.active and promo.current_uses <= promo.max_uses and valid_from <= now <= valid_until

        if not promo_valid:
            raise ApiError("PROMO_CODE_INVALID", "Promo code invalid for recalculation", 422)

        if subtotal < promo.min_order_amount:
            order.promo_code_id = None
            promo.current_uses = max(0, promo.current_uses - 1)
        else:
            if promo.discount_type == api.DiscountType.PERCENTAGE.value:
                discount = min(subtotal * promo.discount_value / Decimal("100"), subtotal * Decimal("0.70"))
            else:
                discount = min(promo.discount_value, subtotal)
            discount = round_money(discount)
            total = round_money(subtotal - discount)

    order.discount_amount = discount
    order.total_amount = total
    db.add(UserOperation(user_id=order.user_id, operation_type=OperationType.UPDATE_ORDER.value))

    db.commit()
    db.refresh(order)
    return to_order_response(order)


@app.post("/orders/{order_id}/cancel", response_model=api.OrderResponse)
def cancel_order(
    order_id: UUID,
    user: User = Depends(require_roles(api.UserRole.USER, api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    order = db.get(Order, str(order_id))
    if not order:
        raise ApiError("ORDER_NOT_FOUND", "Order not found", 404)
    ensure_user_owns_order_or_admin(order, user)

    if order.status not in {api.OrderStatus.CREATED.value, api.OrderStatus.PAYMENT_PENDING.value}:
        raise ApiError("INVALID_STATE_TRANSITION", "Order cannot be canceled in this state", 409)

    for item in order.items:
        product = db.get(Product, item.product_id)
        if product:
            product.stock += item.quantity

    if order.promo_code_id:
        promo = db.get(PromoCode, order.promo_code_id)
        if promo and promo.current_uses > 0:
            promo.current_uses -= 1

    order.status = api.OrderStatus.CANCELED.value
    db.commit()
    db.refresh(order)
    return to_order_response(order)


@app.post("/orders/{order_id}/status", response_model=api.OrderResponse)
def update_order_status(
    order_id: UUID,
    payload: api.OrderStatusUpdateRequest,
    user: User = Depends(require_roles(api.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    transitions = {
        api.OrderStatus.CREATED.value: {api.OrderStatus.PAYMENT_PENDING.value},
        api.OrderStatus.PAYMENT_PENDING.value: {api.OrderStatus.PAID.value, api.OrderStatus.CANCELED.value},
        api.OrderStatus.PAID.value: {api.OrderStatus.SHIPPED.value},
        api.OrderStatus.SHIPPED.value: {api.OrderStatus.COMPLETED.value},
        api.OrderStatus.COMPLETED.value: set(),
        api.OrderStatus.CANCELED.value: set(),
    }

    order = db.get(Order, str(order_id))
    if not order:
        raise ApiError("ORDER_NOT_FOUND", "Order not found", 404)

    if payload.status.value not in transitions.get(order.status, set()):
        raise ApiError("INVALID_STATE_TRANSITION", "Invalid state transition", 409)

    order.status = payload.status.value
    db.commit()
    db.refresh(order)
    return to_order_response(order)
