from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import func

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:postgres@localhost/new_db4'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class SaleOrder(db.Model):
    __tablename__ = 'sale_order'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    date_order = db.Column(db.DateTime)
    amount_total = db.Column(db.Numeric)
    partner_id = db.Column(db.Integer)
    state = db.Column(db.String)

class Partner(db.Model):
    __tablename__ = 'res_partner'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    create_date = db.Column(db.DateTime)

def parse_date(date_str, default):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return default

@app.route('/api/dashboard')
def api_dashboard():
    start_date = parse_date(request.args.get('start_date'), datetime.now() - timedelta(days=30))
    end_date = parse_date(request.args.get('end_date'), datetime.now())

    total_sales = db.session.query(func.coalesce(func.sum(SaleOrder.amount_total), 0)).filter(
        SaleOrder.date_order.between(start_date, end_date)).scalar()

    total_orders = db.session.query(func.count(SaleOrder.id)).filter(
        SaleOrder.date_order.between(start_date, end_date)).scalar()

    avg_order = float(total_sales) / total_orders if total_orders else 0

    new_customers = db.session.query(func.count(Partner.id)).filter(
        Partner.create_date.between(start_date, end_date)).scalar()

    sales_by_status = db.session.query(
        SaleOrder.state,
        func.count(SaleOrder.id),
        func.coalesce(func.sum(SaleOrder.amount_total), 0)
    ).filter(SaleOrder.date_order.between(start_date, end_date)).group_by(SaleOrder.state).all()

    return jsonify({
        "total_sales": float(total_sales),
        "total_orders": total_orders,
        "avg_order": avg_order,
        "new_customers": new_customers,
        "sales_by_status": [
            {"state": s[0] or "Unknown", "count": s[1], "amount": float(s[2])} for s in sales_by_status
        ]
    })

if __name__ == '__main__':
    app.run(debug=True)
