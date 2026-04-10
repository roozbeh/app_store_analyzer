# MongoDB Atlas Setup

Follow these steps to create your free MongoDB Atlas database.

---

## 1. Create an Atlas account & cluster

1. Go to **https://cloud.mongodb.com** and sign up (free).
2. Click **"Build a Database"** → choose **M0 Free Tier** → pick a cloud region close to your users → click **Create**.

---

## 2. Create a database user

1. In the left sidebar go to **Security → Database Access**.
2. Click **"Add New Database User"**.
3. Choose **Password** authentication.
4. Set a username (e.g. `appuser`) and a strong password — **save these**.
5. Under "Database User Privileges" choose **"Read and write to any database"**.
6. Click **Add User**.

---

## 3. Whitelist your IP (or allow all)

1. In the left sidebar go to **Security → Network Access**.
2. Click **"Add IP Address"**.
3. For development or a Docker server, click **"Allow Access from Anywhere"** (`0.0.0.0/0`).
   - For production, add your server's static IP instead.
4. Click **Confirm**.

---

## 4. Get your connection string

1. In the left sidebar go to **Database → Connect** (on your cluster).
2. Click **"Drivers"**.
3. Choose **Python** driver. Copy the connection string — it looks like:
   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
4. Replace `<username>` and `<password>` with the credentials from Step 2.
5. **Add the database name** to the URI so pymongo knows which database to use:
   ```
   mongodb+srv://appuser:yourpassword@cluster0.xxxxx.mongodb.net/app_store_analyzer?retryWrites=true&w=majority
   ```

---

## 5. Add the URI to your backend .env

Open `Backend/.env` (copied from `.env.example`) and set:

```
MONGO_URI=mongodb+srv://appuser:yourpassword@cluster0.xxxxx.mongodb.net/app_store_analyzer?retryWrites=true&w=majority
```

The backend will auto-create the `researches` collection on first write — no migration needed.

---

## 6. Verify (optional)

After starting the backend, hit the health endpoint:

```bash
curl http://localhost:5000/api/health
# → {"status":"ok"}
```

Then create a research via the iOS app (or curl) and check your Atlas dashboard:
- **Database → Browse Collections** → `app_store_analyzer` → `researches`
