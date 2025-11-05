from app import db, User, app

# Run inside the Flask app context
with app.app_context():
    # Drop and recreate all tables
    db.drop_all()
    db.create_all()

    # If your User model has a 'role' column, use it; otherwise skip
    def make_user(username, password, role=None):
        try:
            return User(username=username, password=password, role=role)
        except TypeError:
            # fallback for models without 'role' field
            return User(username=username, password=password)

    # Create users
    admin = make_user("admin", "admin123", "admin")
    desk1 = make_user("desk1", "desk1pass", "desk")
    desk2 = make_user("desk2", "desk2pass", "desk")
    desk3 = make_user("desk3", "desk3pass", "desk")
    desk4 = make_user("desk4", "desk4pass", "desk")

    # Save to DB
    db.session.add_all([admin, desk1, desk2, desk3,desk4])
    db.session.commit()

    print("✅ Database initialized successfully!")
    print("Logins created:")
    print(" - admin / admin123")
    print(" - desk1 / desk1pass")
    print(" - desk2 / desk2pass")
    print(" - desk3 / desk3pass")
    print(" - desk4 / desk4pass")
