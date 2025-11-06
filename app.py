import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# --- Keep users logged in across refreshes ---
app.config['SESSION_COOKIE_NAME'] = 'carnival_tracker_session'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=6)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

@app.before_request
def keep_session_alive():
    session.permanent = True


# -----------------------------
# Database configuration
# -----------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///transactions.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# -----------------------------
# Google Sheets configuration
# -----------------------------
SHEET_NAME = "Carnival_Transactions"
SHEET_SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file("service_account.json", scopes=SHEET_SCOPE)
client = gspread.authorize(creds)
sheet = client.open(SHEET_NAME).sheet1


# -----------------------------
# Database Models
# -----------------------------
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False)
    amount = db.Column(db.Float)
    desk = db.Column(db.String(50))

    # NEW TOKEN FIELDS
    tokens_50 = db.Column(db.Integer, default=0)
    tokens_100 = db.Column(db.Integer, default=0)
    tokens_haunted = db.Column(db.Integer, default=0)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))
    role = db.Column(db.String(20))


# -----------------------------
# Ensure DB Columns Exist
# -----------------------------
def ensure_token_columns():
    with app.app_context():
        engine = db.engine
        dialect = engine.dialect.name

        if dialect == "postgresql":
            stmts = [
                "ALTER TABLE transaction ADD COLUMN IF NOT EXISTS tokens_50 INTEGER DEFAULT 0",
                "ALTER TABLE transaction ADD COLUMN IF NOT EXISTS tokens_100 INTEGER DEFAULT 0",
                "ALTER TABLE transaction ADD COLUMN IF NOT EXISTS tokens_haunted INTEGER DEFAULT 0",
            ]
            for s in stmts:
                engine.execute(text(s))
        else:  # SQLite
            cols = [r[1] for r in engine.execute(text("PRAGMA table_info('transaction')")).fetchall()]
            alters = []
            if "tokens_50" not in cols:
                alters.append("ALTER TABLE transaction ADD COLUMN tokens_50 INTEGER DEFAULT 0")
            if "tokens_100" not in cols:
                alters.append("ALTER TABLE transaction ADD COLUMN tokens_100 INTEGER DEFAULT 0")
            if "tokens_haunted" not in cols:
                alters.append("ALTER TABLE transaction ADD COLUMN tokens_haunted INTEGER DEFAULT 0")
            for s in alters:
                engine.execute(text(s))


# -----------------------------
# Login Route
# -----------------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user'] = username
            if username == 'admin':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('desk'))
        else:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')


# -----------------------------
# Logout Route
# -----------------------------
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))


# -----------------------------
# Desk Route
# -----------------------------
@app.route('/desk', methods=['GET', 'POST'])
def desk():
    if 'user' not in session or session['user'] == 'admin':
        return redirect(url_for('login'))

    username = session['user']

    if request.method == 'POST':
        txn_id = request.form['txn_id'].strip()
        amount = request.form['amount']

        tokens_50 = int(request.form.get('tokens_50') or 0)
        tokens_100 = int(request.form.get('tokens_100') or 0)
        tokens_haunted = int(request.form.get('tokens_haunted') or 0)

        # Prevent duplicate transaction IDs
        existing = Transaction.query.filter_by(transaction_id=txn_id).first()
        if existing:
            flash('Duplicate Transaction ID! Please verify.', 'danger')
            return redirect(url_for('desk'))

        try:
            new_txn = Transaction(
                transaction_id=txn_id,
                amount=amount,
                desk=username,
                tokens_50=tokens_50,
                tokens_100=tokens_100,
                tokens_haunted=tokens_haunted
            )
            db.session.add(new_txn)
            db.session.commit()

            # Append to Google Sheet
            IST = timezone(timedelta(hours=5, minutes=30))
            timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([
                new_txn.id,
                new_txn.transaction_id,
                new_txn.amount,
                new_txn.desk,
                timestamp,
                new_txn.tokens_50,
                new_txn.tokens_100,
                new_txn.tokens_haunted
            ])

            flash('Transaction recorded successfully!', 'success')
            return redirect(url_for('desk'))

        except IntegrityError:
            db.session.rollback()
            flash('Error saving transaction.', 'danger')
            return redirect(url_for('desk'))

    transactions = Transaction.query.filter_by(desk=username).order_by(Transaction.id.asc()).all()
    return render_template('desk.html', user=username, transactions=transactions)


# -----------------------------
# Admin Dashboard
# -----------------------------
@app.route('/admin')
def admin():
    if 'user' not in session or session['user'] != 'admin':
        return redirect(url_for('login'))

    transactions = Transaction.query.order_by(Transaction.id.asc()).all()
    return render_template('admin.html', transactions=transactions)


# -----------------------------
# Admin Delete Transaction
# -----------------------------
@app.route('/delete/<int:txn_id>', methods=['POST'])
def delete_transaction(txn_id):
    if 'user' not in session or session['user'] != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('admin'))

    txn = Transaction.query.get_or_404(txn_id)
    txn_id_str = str(txn.transaction_id)

    db.session.delete(txn)
    db.session.commit()

    try:
        all_values = sheet.get_all_values()
        header = all_values[0]
        txn_col_index = header.index("Transaction ID")

        for i in range(1, len(all_values)):
            if all_values[i][txn_col_index] == txn_id_str:
                sheet.delete_rows(i + 1)
                break
    except Exception as e:
        print(f"⚠️ Error deleting from sheet: {e}")

    flash('Transaction deleted successfully.', 'success')
    return redirect(url_for('admin'))


# -----------------------------
# Run
# -----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_token_columns()
    app.run(debug=True)
