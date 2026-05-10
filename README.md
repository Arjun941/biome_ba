# BiomeBa Backend

> **Gamified Biodiversity Social Platform** — Flask + MongoDB REST API

A production-style Flask backend for BiomeBa: upload wildlife observations, identify species with a ConvNeXt-Large-MLP model trained on iNat2021, earn XP, complete missions, and connect with fellow naturalists.

---

## 🗂 Project Structure

```
biome_ba/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── config.py            # Environment-aware config classes
│   ├── extensions.py        # PyMongo, JWT, Limiter singletons
│   ├── routes/              # Blueprint route handlers
│   │   ├── auth.py          # /auth/*
│   │   ├── profile.py       # /profile/*
│   │   ├── species.py       # /identify, /observations/*
│   │   ├── missions.py      # /missions/*
│   │   ├── leaderboard.py   # /leaderboard/*
│   │   ├── social.py        # /posts/*
│   │   └── search.py        # /search/*
│   ├── models/              # MongoDB document schema factories
│   ├── services/            # Business logic layer
│   │   ├── rarity_service.py
│   │   ├── xp_service.py
│   │   ├── mission_service.py
│   │   └── notification_service.py
│   ├── ml/
│   │   └── inference.py     # ONNX model singleton
│   ├── middleware/
│   │   └── auth_middleware.py   # @token_required decorator
│   └── utils/               # Validators, pagination, geo, serializers
├── scripts/
│   ├── seed_missions.py
│   └── seed_species_meta.py
├── model_fp16.onnx          # ONNX FP16 ConvNeXt model (not in git)
├── config.json              # Model config (label names, architecture)
├── run.py                   # Entry point
├── requirements.txt
└── .env.example
```

---

## ⚡ Quick Start

### 1. Prerequisites

- Python 3.11+
- MongoDB (local `mongod` or Atlas connection string)
- The `model_fp16.onnx` and `config.json` files in the project root

### 2. Clone & Set Up Virtual Environment

```bash
cd d:\biome_ba
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
copy .env.example .env
# Edit .env with your MongoDB URI and secret keys
```

Key variables in `.env`:
```env
MONGO_URI=mongodb://localhost:27017/biome_ba
JWT_SECRET_KEY=your-very-long-random-secret
SECRET_KEY=another-random-secret
```

### 5. Seed the Database

```bash
python scripts/seed_missions.py
python scripts/seed_species_meta.py
```

### 6. Run the Server

```bash
python run.py
```

Server starts at `http://localhost:5000`

---

## 📖 API Documentation

Interactive Swagger UI: **`http://localhost:5000/apidocs`**

### Auth Routes

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/auth/register` | No | Register new user |
| POST | `/auth/login` | No | Login, get JWT |
| GET | `/auth/me` | ✅ | Current user profile |
| POST | `/auth/refresh` | Refresh token | New access token |

### Profile Routes

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/profile/<user_id>` | No | Public profile |
| PUT | `/profile/edit` | ✅ | Edit own profile |
| POST | `/profile/follow/<user_id>` | ✅ | Follow/unfollow user |
| GET | `/profile/notifications` | ✅ | User notifications |

### Species & Observations

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/identify` | ✅ | Run species ID on base64 image |
| POST | `/observations` | ✅ | Save observation |
| GET | `/observations/<id>` | No | Get observation |
| GET | `/observations/nearby?lat=&lng=&radius_km=` | No | Nearby observations |
| GET | `/observations/species/<name>` | No | Species observations |
| GET | `/observations/user/<user_id>` | No | User's observations |
| DELETE | `/observations/<id>` | ✅ | Delete own observation |
| POST | `/observations/<id>/like` | ✅ | Toggle like |

### Missions

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/missions?type=daily` | ✅ | List missions + progress |
| GET | `/missions/progress` | ✅ | User's progress |
| POST | `/missions/claim` | ✅ | Claim reward |

### Leaderboards

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/leaderboard/global` | No | Global XP leaderboard |
| GET | `/leaderboard/country/<country>` | No | Country leaderboard |
| GET | `/leaderboard/local/<district>` | No | District leaderboard |

### Social

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| POST | `/posts` | ✅ | Create post |
| GET | `/posts/feed` | Optional | Paginated feed |
| GET | `/posts/<id>` | No | Single post + comments |
| POST | `/posts/<id>/comment` | ✅ | Add comment |
| POST | `/posts/<id>/like` | ✅ | Toggle like |
| POST | `/posts/<id>/react` | ✅ | Emoji reaction |
| DELETE | `/posts/<id>` | ✅ | Delete post |

### Search

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| GET | `/search/users?q=` | No | Search users |
| GET | `/search/species?q=` | No | Search species |
| GET | `/search/posts?q=` | No | Search posts |

---

## 🔐 Authentication

All protected routes require the `Authorization` header:
```
Authorization: Bearer <access_token>
```

Tokens expire after **24 hours**. Use `POST /auth/refresh` with your refresh token to get a new access token.

---

## 🧪 Example Requests

### Register
```bash
curl -X POST http://localhost:5000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"arjun941","email":"arjun@example.com","password":"securepass","country":"India"}'
```

### Identify Species
```bash
curl -X POST http://localhost:5000/identify \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"image_base64":"<base64_string>","top_k":5}'
```

### Nearby Observations
```bash
curl "http://localhost:5000/observations/nearby?lat=12.9716&lng=77.5946&radius_km=50&limit=10"
```

---

## 🛠 Architecture Notes

- **App factory pattern**: `create_app()` in `app/__init__.py`
- **Blueprints**: Each feature domain is a separate blueprint
- **ML model**: Loaded once at startup as an ONNX FP16 session; thread-safe via `threading.Lock()`
- **Images**: All stored as base64 strings in MongoDB (no external storage)
- **Rarity engine**: 5-component weighted scoring (global, local, seasonal, conservation, uniqueness)
- **XP system**: Tier-scaled rewards; quadratic level thresholds
- **Rate limiting**: Per-IP via `flask-limiter`; `memory://` storage (swap to Redis in production)

---

## 🚀 Production Deployment

1. Set `FLASK_ENV=production` in `.env`
2. Use **Gunicorn**: `gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"`
3. Set up **Redis** for rate limiting: `REDIS_URL=redis://localhost:6379`
4. Use **MongoDB Atlas** for the hosted database
5. Put behind **Nginx** as a reverse proxy
6. Set strong random values for `SECRET_KEY` and `JWT_SECRET_KEY`
