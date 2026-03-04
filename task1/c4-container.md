# C4 Container Diagram (Text Version)

## 1) People and External Systems
- Buyer
- Seller
- Payment Provider (external)
- Email/SMS Provider (external)

## 2) System Boundary: Marketplace

```text
Buyer/Seller
    |
    v
Web/Mobile UI
    |
    v (HTTPS)
API Gateway
    |----> Feed Service ---------> Feed DB
    |----> Catalog Service ------> Catalog DB
    |----> User Service ---------> User DB
    |----> Order Service --------> Order DB
                     |
                     | Sync: create payment
                     v
               Payment Service ----> Payment DB ----> Payment Provider

Order Service ----\
Payment Service ---+--> Message Bus --> Notification Service --> Notification DB --> Email/SMS Provider
Catalog Service ---/
```

## 3) Containers and Responsibilities

| Container | Tech | Responsibility |
|---|---|---|
| Web/Mobile UI | SPA/Mobile | Interface for buyers and sellers |
| API Gateway | FastAPI | Single entry point, routing, auth, rate limiting |
| Feed Service | Service | Personalized product feed |
| Catalog Service | Service | Product listings, categories, search indexes |
| User Service | Service | Profiles, roles, seller accounts |
| Order Service | Service | Checkout and order lifecycle |
| Payment Service | Service | Payment intents, settlements, ledger |
| Notification Service | Service | Order status notifications |
| Message Bus | Kafka/RabbitMQ | Asynchronous event delivery |

## 4) Data Ownership

| Service | Owned Data Store |
|---|---|
| Feed Service | Feed DB (PostgreSQL/Redis) |
| Catalog Service | Catalog DB (PostgreSQL) |
| User Service | User DB (PostgreSQL) |
| Order Service | Order DB (PostgreSQL) |
| Payment Service | Payment DB (PostgreSQL) |
| Notification Service | Notification DB (PostgreSQL) |

No shared databases between services.

## 5) Relationships
- Buyer -> Web/Mobile UI (`uses`)
- Seller -> Web/Mobile UI (`uses`)
- Web/Mobile UI -> API Gateway (`HTTPS`)
- API Gateway -> Feed/Catalog/User/Order Services (`REST/gRPC`, synchronous)
- Order Service -> Payment Service (`synchronous`, create payment)
- Payment Service -> Payment Provider (`synchronous`)
- Order Service -> Message Bus (`asynchronous`, order events)
- Payment Service -> Message Bus (`asynchronous`, payment events)
- Catalog Service -> Message Bus (`asynchronous`, catalog updates)
- Message Bus -> Notification Service (`asynchronous`, event consumption)
- Notification Service -> Email/SMS Provider (`send notifications`)
