import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # change before deployment

# -----------------------------
# Database configuration
# -----------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///transactions.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -----------------------------
# Google Sheets configuration
# -----------------------------
SHEET_NAME = "Carnival_Transactions"  # Your sheet name
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


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(50))
    # optional role field
    try:
        role = db.Column(db.String(20))
    except Exception:
        pass


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
        txn_id = request.form['txn_id']
        amount = request.form['amount']

        # Prevent duplicate transaction IDs
        existing = Transaction.query.filter_by(transaction_id=txn_id).first()
        if existing:
            flash('Duplicate Transaction ID! Please verify.', 'danger')
        else:
            try:
                new_txn = Transaction(transaction_id=txn_id, amount=amount, desk=username)
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
                    timestamp
                ])

                flash('Transaction recorded successfully!', 'success')
            except IntegrityError:
                db.session.rollback()
                flash('Error saving transaction.', 'danger')

    transactions = Transaction.query.filter_by(desk=username).all()
    return render_template('desk.html', user=username, transactions=transactions)


# -----------------------------
# Admin Dashboard
# -----------------------------
@app.route('/admin')
def admin():
    if 'user' not in session or session['user'] != 'admin':
        return redirect(url_for('login'))

    transactions = Transaction.query.all()
    return render_template('admin.html', transactions=transactions)


# -----------------------------
# Admin Delete Transaction
# -----------------------------
@app.route('/delete/<int:txn_id>', methods=['POST'])
def delete_transaction(txn_id):
    if 'user' not in session or session['user'] != 'admin':
        flash('Unauthorized access', 'danger')
        return redirect(url_for('admin'))

    # Fetch the transaction first
    txn = Transaction.query.get_or_404(txn_id)
    txn_id_str = str(txn.transaction_id)

    # Delete from database
    db.session.delete(txn)
    db.session.commit()

    # Also delete from Google Sheet
    try:
        all_values = sheet.get_all_values()
        header = all_values[0]
        txn_col_index = header.index("Transaction ID")

        for i in range(1, len(all_values)):
            if all_values[i][txn_col_index] == txn_id_str:
                sheet.delete_rows(i + 1)  # +1 because sheet rows are 1-indexed
                print(f"✅ Deleted transaction {txn_id_str} from Google Sheet.")
                break
        else:
            print(f"⚠️ Transaction {txn_id_str} not found in sheet.")
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
    app.run(debug=True)
