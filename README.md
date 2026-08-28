# ReClaim — Smart Lost & Found Web Platform

**ReClaim** is a modern full-stack web application designed for campus and community environments to report, discover, match, and recover lost items securely and efficiently.

---

## 🌟 Key Features

- **Smart Multi-Factor Matching Engine**: Automatically compares lost and found listings using fuzzy string matching across title, category, description, and location to calculate real-time similarity scores.
- **Automated Alerts & Notifications**: In-app and automated SMTP email alerts when potential matches are identified.
- **Reunited Success Stories Showcase & Archive**: Real-time showcase on the homepage celebrating recovered items and a full searchable resolution archive (`/reclaimed`).
- **Printable Missing Item Flyer Generator**: 1-click generation of high-resolution A4 posters with dynamic QR codes and tear-off contact strips for physical bulletin boards (`/item/<type>/<id>/flyer`).
- **Smart QR Item Tags Maker**: Preventative asset protection allowing users to generate printable sticker sheets of QR codes for laptops, keys, and water bottles before loss (`/qr-tags`).
- **Community Hall of Fame & Leaderboard**: Gamified reputation scoring and podium honoring good Samaritans with badges (*Community Hero*, *Helpful Finder*) (`/leaderboard`).
- **Anti-Fraud Ownership Claims**: Item posters can lock contact details behind verification questions, requiring claimants to verify ownership before private details are unlocked.
- **Interactive Geospatial Campus Map**: Visualizes lost and found items on an interactive Leaflet.js map with coordinate mapping and campus presets.
- **In-App Direct Messaging**: Built-in chat system allowing finders and owners to coordinate returns safely.
- **Admin Moderation Panel**: Content flagging, report moderation, user reputation metrics, and administrative role management.
- **Modern Responsive UI**: Clean light/dark mode design system built with vanilla CSS and responsive components.


---

## 🛠️ Tech Stack

- **Backend**: Python, Flask, SQLite3, Werkzeug
- **Frontend**: HTML5, CSS3 (Custom Design System, Light/Dark theme), JavaScript (ES6+)
- **GIS / Mapping**: Leaflet.js
- **Icons & Fonts**: FontAwesome 6, Google Fonts

---

## 🚀 Getting Started Locally

### 1. Prerequisites
- Python 3.9 or newer installed on your machine.
- Git installed.

### 2. Clone the Repository
```bash
git clone https://github.com/<YOUR-USERNAME>/<YOUR-REPO-NAME>.git
cd <YOUR-REPO-NAME>
```

### 3. Set up a Virtual Environment (Recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Run the Application
```bash
python app.py
```
Open your browser and navigate to: **`http://127.0.0.1:5000`**

---

## ⚙️ Environment Variables (Optional)

You can configure the following environment variables if you want to enable live email delivery:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask session secret key |
| `MATCH_NOTIFY_THRESHOLD` | Match percentage score threshold for alert triggers (default: `60`) |
| `SMTP_HOST` | SMTP server hostname (e.g., `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (e.g., `587`) |
| `SMTP_USER` | SMTP username/email address |
| `SMTP_PASS` | SMTP app password |
| `EMAIL_FROM` | Sender email address |

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
