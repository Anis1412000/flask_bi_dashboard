from flask import Flask, render_template_string, request, jsonify, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from collections import Counter
from sqlalchemy import extract
from io import StringIO
import csv
import random
import re
from dateutil.relativedelta import relativedelta
from calendar import monthrange
import math

app = Flask(__name__)

# Database configuration - UPDATE YOUR CREDENTIALS HERE
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:postgres@localhost/new_db4'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class SaleOrder(db.Model):
    __tablename__ = 'sale_order'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    date_order = db.Column(db.DateTime)
    amount_total = db.Column(db.Numeric)
    partner_id = db.Column(db.Integer)
    state = db.Column(db.String)  # Added for status tracking

class Partner(db.Model):
    __tablename__ = 'res_partner'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    create_date = db.Column(db.DateTime)

class ProductTemplate(db.Model):
    __tablename__ = 'product_template'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    list_price = db.Column(db.Numeric)
    create_date = db.Column(db.DateTime)  # <-- This is required!
    # Add more fields if needed

class Product(db.Model):
    __tablename__ = 'product_product'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    product_tmpl_id = db.Column(db.Integer, db.ForeignKey('public.product_template.id'))
    default_code = db.Column(db.String)
    template = db.relationship('ProductTemplate', backref='products')
    # Remove name field (not present)

class SaleOrderLine(db.Model):
    __tablename__ = 'sale_order_line'
    __table_args__ = {'schema': 'public'}
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('public.sale_order.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('public.product_product.id'))
    price_subtotal = db.Column(db.Numeric)
    product = db.relationship('Product')

# Dashboard route with ALL visualizations
@app.route('/')
def dashboard():
    # Date filtering
    default_end = datetime.now()
    default_start = default_end - timedelta(days=30)
    start_date = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', default_end.strftime('%Y-%m-%d'))

    # Main KPIs
    total_sales = db.session.query(db.func.sum(SaleOrder.amount_total)).filter(
        SaleOrder.date_order.between(start_date, end_date)).scalar() or 0
    order_count = db.session.query(db.func.count(SaleOrder.id)).filter(
        SaleOrder.date_order.between(start_date, end_date)).scalar()
    # Calculate average order value, rounded to 2 decimals for a cooler display
    avg_order = round(total_sales / order_count, 2) if order_count > 0 else 0
    new_customers = db.session.query(db.func.count(Partner.id)).filter(
        Partner.create_date.between(start_date, end_date)).scalar()

    # Top customers
    top_customers = db.session.query(
        Partner.name,
        db.func.sum(SaleOrder.amount_total).label('total')
    ).join(SaleOrder, Partner.id == SaleOrder.partner_id).filter(
        SaleOrder.date_order.between(start_date, end_date)
    ).group_by(Partner.name).order_by(db.desc('total')).limit(5).all()

    # Top products by revenue
    top_products = db.session.query(
        ProductTemplate.name,
        db.func.sum(SaleOrderLine.price_subtotal).label('total_revenue')
    ).join(Product, ProductTemplate.id == Product.product_tmpl_id)\
     .join(SaleOrderLine, SaleOrderLine.product_id == Product.id)\
     .join(SaleOrder, SaleOrder.id == SaleOrderLine.order_id)\
     .filter(SaleOrder.date_order.between(start_date, end_date))\
     .group_by(ProductTemplate.name)\
     .order_by(db.desc('total_revenue'))\
     .limit(5).all()

    # Sales by status
    status_data = db.session.query(
        SaleOrder.state,
        db.func.count(SaleOrder.id),
        db.func.sum(SaleOrder.amount_total)
    ).filter(SaleOrder.date_order.between(start_date, end_date)).group_by(SaleOrder.state).all()

    # Before rendering the dashboard template, convert status_data and top_customers to lists of tuples
    status_data = [tuple(row) for row in status_data]
    top_customers = [tuple(row) for row in top_customers]

    # --- NEW CHARTS DATA ---
    # 1. Sales by Day of Week (Radar Chart)
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    sales_by_day_q = db.session.query(
        extract('isodow', SaleOrder.date_order),
        db.func.sum(SaleOrder.amount_total)
    ).filter(SaleOrder.date_order.between(start_date, end_date)).group_by(extract('isodow', SaleOrder.date_order)).all()
    sales_by_day = {day: 0.0 for day in days}
    for day_num, total in sales_by_day_q:
        if day_num and total:
            sales_by_day[days[int(day_num) - 1]] = float(total)
    radar_chart_labels = list(sales_by_day.keys())
    radar_chart_data = list(sales_by_day.values())

    # 2. Order Value Distribution (Histogram)
    amounts = [float(a[0]) for a in db.session.query(SaleOrder.amount_total).filter(SaleOrder.date_order.between(start_date, end_date)).all() if a[0] is not None]
    max_amount = max(amounts) if amounts else 1.0
    bucket_size = max(1.0, max_amount / 10)
    buckets = Counter(int(min(max_amount - 1, amount) // bucket_size) for amount in amounts)
    histogram_labels = [f"${i*bucket_size:,.0f} - ${(i+1)*bucket_size:,.0f}" for i in range(10)]
    histogram_data = [buckets.get(i, 0) for i in range(10)]

    # 3. Sales Funnel
    status_order = ['draft', 'sent', 'sale', 'done', 'cancel']
    funnel_data_map = {s[0]: s[1] for s in status_data if s[0] in status_order}
    funnel_labels = [s.capitalize() for s in status_order if s in funnel_data_map]
    funnel_data = [funnel_data_map.get(s, 0) for s in status_order if s in funnel_data_map]
    
    # 4. Average Order Value Over Time
    aov_labels, aov_data = [], []
    today = datetime.now()
    for i in range(5, -1, -1):
        target_date = today - timedelta(days=i * 30)
        year, month = target_date.year, target_date.month
        monthly_sales = db.session.query(db.func.sum(SaleOrder.amount_total), db.func.count(SaleOrder.id)).filter(extract('year', SaleOrder.date_order) == year, extract('month', SaleOrder.date_order) == month).first()
        
        aov_labels.append(target_date.strftime('%Y-%m'))
        if monthly_sales and monthly_sales[1] and monthly_sales[1] > 0:
            total, count = monthly_sales[0] or 0, monthly_sales[1]
            aov_data.append(float(total / count))
        else:
            aov_data.append(0)

    # Pagination parameters
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))

    # Count total recent orders for pagination
    total_recent_orders = db.session.query(SaleOrder).filter(
        SaleOrder.date_order.between(start_date, end_date)
    ).count()
    total_pages = (total_recent_orders + per_page - 1) // per_page

    # Recent orders with pagination
    recent_orders = db.session.query(SaleOrder, Partner.name).join(
        Partner, SaleOrder.partner_id == Partner.id
    ).filter(SaleOrder.date_order.between(start_date, end_date)).order_by(
        SaleOrder.date_order.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()

    # Top clients by revenue
    top_clients_by_revenue = db.session.query(
        Partner.name,
        db.func.sum(SaleOrder.amount_total).label('total_revenue')
    ).join(SaleOrder, Partner.id == SaleOrder.partner_id)\
    .filter(SaleOrder.date_order.between(start_date, end_date))\
    .group_by(Partner.name)\
    .order_by(db.desc('total_revenue'))\
    .limit(10)\
    .all()
    
    top_clients_by_revenue = [tuple(row) for row in top_clients_by_revenue]

    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>Advanced Odoo Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0"></script>
    <style>
        :root {
            --primary: #4361ee;
            --secondary: #3a0ca3;
            --success: #4cc9f0;
            --danger: #f72585;
            --warning: #f8961e;
            --dark: #212529;
            --bg: #f4f6fb;
            --card-bg: #fff;
            --border: #e0e3eb;
            --shadow: 0 4px 24px rgba(67, 97, 238, 0.07);
        }
        html, body {
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            background: var(--bg);
            margin: 0;
            padding: 0;
            color: var(--dark);
        }
        .header {
            position: sticky;
            top: 0;
            z-index: 10;
            background: var(--card-bg);
            box-shadow: 0 2px 8px rgba(67, 97, 238, 0.04);
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 24px 32px 18px 32px;
            margin-bottom: 32px;
        }
        .header h1 {
            font-size: 2.2rem;
            font-weight: 700;
            margin: 0;
            letter-spacing: -1px;
            user-select: text;
        }
        .date-filter {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .date-filter input[type="date"] {
            padding: 10px 14px;
            border-radius: 6px;
            border: 1px solid var(--border);
            font-size: 1rem;
            background: #f9fafe;
            transition: border 0.2s;
        }
        .date-filter input[type="date"]:focus {
            border: 1.5px solid var(--primary);
            outline: none;
        }
        .date-filter button {
            padding: 10px 20px;
            border-radius: 6px;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            color: #fff;
            border: none;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(67, 97, 238, 0.08);
            transition: background 0.2s, box-shadow 0.2s;
        }
        .date-filter button:hover {
            background: linear-gradient(90deg, var(--secondary), var(--primary));
            box-shadow: 0 4px 16px rgba(67, 97, 238, 0.13);
        }
        .kpi-container {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 28px;
            margin-bottom: 36px;
        }
        .kpi-card {
            background: var(--card-bg);
            border-radius: 14px;
            padding: 28px 24px 22px 24px;
            box-shadow: var(--shadow);
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            transition: transform 0.13s, box-shadow 0.13s;
        }
        .kpi-card:hover {
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 8px 32px rgba(67, 97, 238, 0.13);
        }
        .kpi-card > div:first-child,
        .kpi-value,
        .kpi-card > div:last-child,
        th {
            user-select: text;
        }
        .kpi-card > div:first-child {
            font-size: 1.1rem;
            color: var(--secondary);
            font-weight: 600;
        }
        .kpi-value {
            font-size: 2.1rem;
            font-weight: 700;
            margin: 12px 0 8px 0;
            color: var(--dark);
            min-height: 2.5rem;
        }
        .kpi-card > div:last-child {
            font-size: 1rem;
            color: #7b809a;
        }
        .chart-row {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 28px;
            margin-bottom: 28px;
        }
        .chart-card {
            background: var(--card-bg);
            border-radius: 14px;
            padding: 28px 24px 22px 24px;
            box-shadow: var(--shadow);
            margin-bottom: 0;
        }
        .chart-title {
            margin-top: 0;
            color: var(--secondary);
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 18px;
            user-select: text;
        }
        table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 18px;
            background: var(--card-bg);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: var(--shadow);
        }
        th, td {
            padding: 14px 18px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        th {
            background: #f5f7fa;
            font-weight: 600;
            color: var(--secondary);
            font-size: 1.05rem;
        }
        tr:last-child td {
            border-bottom: none;
        }
        .badge {
            padding: 5px 12px;
            border-radius: 14px;
            font-size: 0.98rem;
            font-weight: 600;
            color: #fff;
            letter-spacing: 0.5px;
        }
        .badge-success { background: var(--success); }
        .badge-warning { background: var(--warning); }
        .badge-danger { background: var(--danger); }
        @media (max-width: 1100px) {
            .kpi-container, .chart-row { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 700px) {
            .header { flex-direction: column; align-items: flex-start; padding: 18px 10px 12px 10px; }
            .kpi-container, .chart-row { grid-template-columns: 1fr; gap: 18px; }
            .chart-card, .kpi-card { padding: 18px 10px 14px 10px; }
            table, th, td { font-size: 0.98rem; }
        }
        .navbar {
            width: 100%;
            background: var(--primary);
            color: #fff;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 0 0 0 0;
            min-height: 48px;
            font-size: 1.08rem;
            font-weight: 600;
            letter-spacing: 0.5px;
            box-shadow: 0 2px 8px rgba(67, 97, 238, 0.08);
        }
        .navbar a {
            color: #fff;
            text-decoration: none;
            padding: 0 28px;
            line-height: 48px;
            transition: background 0.2s, color 0.2s;
        }
        .navbar a:hover, .navbar a.active {
            background: var(--secondary);
            color: #fff;
        }
        @media (max-width: 700px) {
            .navbar { font-size: 0.98rem; }
            .navbar a { padding: 0 12px; }
        }
        .chart-container {
            min-height: 500px;
            border: 4px solid #4361ee;
            border-radius: 18px;
            box-shadow: 0 8px 32px rgba(67,97,238,0.13);
            background: #23244d;
            margin-bottom: 32px;
            padding: 32px 24px 24px 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        canvas { max-width: 100%; width: 1000px !important; height: 500px !important; }
        .chart-slider-container {
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 32px 0 48px 0;
        }
        .slider-arrow {
            background: linear-gradient(90deg,#4361ee,#f72585);
            color: #fff;
            border: none;
            border-radius: 50%;
            width: 48px;
            height: 48px;
            font-size: 2rem;
            font-weight: bold;
            cursor: pointer;
            margin: 0 18px;
            box-shadow: 0 2px 8px #4cc9f0;
            transition: background 0.2s;
        }
        .slider-arrow:hover {
            background: linear-gradient(90deg,#f72585,#4361ee);
        }
        .chart-slider {
            width: 1000px;
            height: 500px;
            overflow: hidden;
            position: relative;
            display: flex;
        }
        .slide {
            min-width: 100%;
            transition: transform 0.5s cubic-bezier(.77,0,.18,1);
            display: none;
            justify-content: center;
            align-items: center;
        }
        .slide.active {
            display: flex;
        }
        .chart-slider canvas {
            width: 1000px !important;
            height: 500px !important;
            background: #23244d;
            border-radius: 18px;
            box-shadow: 0 8px 32px rgba(67,97,238,0.13);
            border: 2px solid #fff;
        }
        .empty-state {
            width: 1000px;
            height: 500px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: #23244d;
            border-radius: 18px;
            border: 2px dashed #4cc9f0;
            color: #4cc9f0;
            font-size: 2rem;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 #4cc9f055; }
            70% { box-shadow: 0 0 0 16px #4cc9f000; }
            100% { box-shadow: 0 0 0 0 #4cc9f000; }
        }
    </style>
</head>
<body>
    <div class="navbar">
        <a href="/products" {% if request.path == '/products' %}class="active"{% endif %}>Products</a>
        <a href="/sales-orders" {% if request.path == '/sales-orders' or request.path == '/' %}class="active"{% endif %}>Sales Orders</a>
        <a href="/clients" {% if request.path == '/clients' %}class="active"{% endif %}>Clients</a>
    </div>
    <div class="header">
        <h1>📊 Odoo Sales Dashboard</h1>
        <div class="date-filter">
            <input type="date" id="startDate" value="{{ start_date }}">
            <span>to</span>
            <input type="date" id="endDate" value="{{ end_date }}">
            <button onclick="applyFilter()">Apply</button>
        </div>
    </div>

    <!-- KPI Cards -->
    <div class="kpi-container">
        <div class="kpi-card">
            <div>Total Sales</div>
            <div class="kpi-value" id="kpi-total-sales">${{ "{:,.2f}".format(total_sales) }}</div>
            <div>📈 12% increase</div>
        </div>
        <div class="kpi-card">
            <div>Total Orders</div>
            <div class="kpi-value" id="kpi-order-count">{{ order_count }}</div>
            <div>📊 {{ "{:,.0f}".format(order_count/30) }}/day</div>
        </div>
        <div class="kpi-card">
            <div>Avg. Order</div>
            <div class="kpi-value" id="kpi-avg-order">${{ "{:,.2f}".format(avg_order) }}</div>
            <div>💰 {{ "{:.0f}".format(avg_order/100) }}x target</div>
        </div>
        <div class="kpi-card">
            <div>New Customers</div>
            <div class="kpi-value" id="kpi-new-customers">{{ new_customers }}</div>
            <div>👥 15% growth</div>
        </div>
    </div>

    <!-- Add Sales Heatmap and Gauge containers to the slider -->
    <div class="chart-slider-container">
        <button class="slider-arrow left" onclick="prevSlide()">&#8592;</button>
        <div class="chart-slider">
            <div class="slide active">
                <canvas id="salesTrendChart" width="600" height="400" style="display:block;"></canvas>
            </div>
            <div class="slide">
                <canvas id="salesStatusPieChart" width="600" height="400" style="display:block;"></canvas>
            </div>
            <div class="slide">
                <canvas id="mostProfitableClientsChart" width="600" height="400" style="display:block;"></canvas>
            </div>
            <div class="slide">
                <canvas id="mostActiveClientsChart" width="600" height="400" style="display:block;"></canvas>
            </div>
            <div class="slide">
                <canvas id="statusChart" width="600" height="400" style="display:block;"></canvas>
            </div>
        </div>
        <button class="slider-arrow right" onclick="nextSlide()">&#8594;</button>
    </div>

    <!-- Recent Orders Table -->
    <div class="chart-card" style="margin-top: 32px;">
        <h3 class="chart-title">Recent Orders</h3>
        <table>
            <thead>
                <tr>
                    <th>Order</th>
                    <th>Date</th>
                    <th>Customer</th>
                    <th>Amount</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for order, customer in recent_orders %}
                <tr>
                    <td>{{ order.name }}</td>
                    <td>{{ order.date_order.strftime('%Y-%m-%d') }}</td>
                    <td>{{ customer }}</td>
                    <td>${{ "{:,.2f}".format(order.amount_total) }}</td>
                    <td>
                        <span class="badge {% if order.state == 'sale' %}badge-success{% elif order.state == 'draft' %}badge-warning{% else %}badge-danger{% endif %}">
                            {{ order.state or 'N/A' }}
                        </span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <div style="margin-top: 16px; text-align: right;">
        {% if page > 1 %}
            <a href="{{ url_for('dashboard', start_date=start_date, end_date=end_date, page=page-1, per_page=per_page) }}" style="margin-right: 8px;">&laquo; Previous</a>
        {% endif %}
        Page {{ page }} of {{ total_pages }}
        {% if page < total_pages %}
            <a href="{{ url_for('dashboard', start_date=start_date, end_date=end_date, page=page+1, per_page=per_page) }}" style="margin-left: 8px;">Next &raquo;</a>
        {% endif %}
    </div>

    <script>
        function applyFilter() {
            const start = document.getElementById('startDate').value;
            const end = document.getElementById('endDate').value;
            window.location.href = `/?start_date=${start}&end_date=${end}`;
        }

        // KPI Animation
        function animateKPI(id, end, prefix = '', suffix = '', decimals = 0) {
            const el = document.getElementById(id);
            if (!el) return;
            let start = 0;
            const duration = 900;
            const step = Math.max(1, Math.floor(end / 60));
            let current = start;
            const increment = () => {
                current += step;
                if ((step > 0 && current >= end) || (step < 0 && current <= end)) current = end;
                el.textContent = prefix + current.toLocaleString(undefined, {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + suffix;
                if (current !== end) requestAnimationFrame(increment);
            };
            increment();
        }
        document.addEventListener('DOMContentLoaded', function() {
            const statusOrder = ["Draft", "Sent", "Sale", "Done", "Cancel"];
            // Animate KPIs
            animateKPI('kpi-total-sales', Number({{ total_sales }}), '$', '', 2);
            animateKPI('kpi-order-count', Number({{ order_count }}));
            animateKPI('kpi-avg-order', Number({{ avg_order }}), '$', '', 2);
            animateKPI('kpi-new-customers', Number({{ new_customers }}));

            // --- Inject sample data for demo if empty ---
            let salesData = {{ trendData.data|tojson if trendData and trendData.data else 'null' }};
            let salesLabels = {{ trendData.labels|tojson if trendData and trendData.labels else 'null' }};
            if (!salesData || salesData.length === 0) {
                salesLabels = Array.from({length: 30}, (_, i) => {
                    const d = new Date();
                    d.setDate(d.getDate() - 30 + i);
                    return d.toLocaleDateString();
                });
                salesData = Array.from({length: 30}, () => Math.floor(Math.random() * 10000) + 1000);
            }
            // Sales Trend Chart (animated area)
            const trendCtx = document.getElementById('trendChart').getContext('2d');
            const grad = trendCtx.createLinearGradient(0, 0, 0, 500);
            grad.addColorStop(0, '#4cc9f0cc');
            grad.addColorStop(1, '#4361ee11');
            new Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: salesLabels,
                    datasets: [{
                        label: 'Daily Sales',
                        data: salesData,
                        borderColor: '#4cc9f0',
                        backgroundColor: grad,
                        tension: 0.4,
                        fill: true,
                        pointRadius: 0,
                        borderWidth: 4
                    }]
                },
                options: {
                    responsive: true,
                    animation: { duration: 1800, easing: 'easeInOutQuart' },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: (ctx) => '$' + ctx.raw.toLocaleString()
                            }
                        },
                        title: {
                            display: true,
                            text: 'Sales Trend',
                            color: '#4cc9f0',
                            font: { size: 32, weight: 'bold', family: 'Inter' }
                        }
                    },
                    scales: {
                        y: {
                            ticks: {
                                color: '#fff',
                                callback: (value) => '$' + value.toLocaleString()
                            },
                            grid: { color: '#4cc9f055' }
                        },
                        x: {
                            ticks: { color: '#fff' },
                            grid: { color: '#4cc9f022' }
                        }
                    }
                }
            });
            // Orders Radial Bar (Polar Area) - always show all statuses in logical order
            // Add hint tooltip on hover
            const statusChartCanvas = document.getElementById('statusChart');
            if (statusChartCanvas) {
                statusChartCanvas.title = 'This chart shows the distribution of your orders by status. If only one status is present, the whole pie will be that status.';
            }
            let orderDataRaw = {{ status_data|tojson if status_data else '[]' }};
            let orderCounts = {};
            if (orderDataRaw && orderDataRaw.length > 0) {
                for (const s of orderDataRaw) {
                    orderCounts[(s[0] || '').charAt(0).toUpperCase() + (s[0] || '').slice(1)] = s[1];
                }
            }
            let orderData = statusOrder.map(s => orderCounts[s] || 0);
            let orderLabels = statusOrder;
            let totalOrders = orderData.reduce((a, b) => a + b, 0);
            let nonZeroStatuses = orderData.filter(x => x > 0).length;
            let chartType = (nonZeroStatuses === 1) ? 'pie' : 'polarArea';
            let pieColors = ['#4cc9f0', '#4361ee', '#f72585', '#f8961e', '#3a0ca3'];
            let usedColors = [];
            if (chartType === 'pie') {
                // Only show the nonzero status as a full pie
                let idx = orderData.findIndex(x => x > 0);
                orderData = [orderData[idx]];
                orderLabels = [statusOrder[idx]];
                usedColors = [pieColors[idx]];
            } else {
                usedColors = pieColors;
            }
            if (totalOrders === 0) {
                orderData = [5, 8, 12, 7, 2];
                orderLabels = statusOrder;
                usedColors = pieColors;
                totalOrders = orderData.reduce((a, b) => a + b, 0);
                chartType = 'polarArea';
            }
            new Chart(document.getElementById('statusChart'), {
                type: chartType,
                data: {
                    labels: orderLabels,
                    datasets: [{
                        data: orderData,
                        backgroundColor: usedColors
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'right', labels: { color: '#fff', font: { size: 18 } } },
                        title: {
                            display: true,
                            text: 'Orders by Status',
                            color: '#f72585',
                            font: { size: 28, weight: 'bold', family: 'Inter' }
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const count = context.raw;
                                    const percent = totalOrders > 0 ? Math.round(100 * count / totalOrders) : 0;
                                    return `${context.label}: ${count} orders (${percent}%)`;
                                }
                            }
                        }
                    }
                }
            });
            // Empty state for customersChart and revenueChart
            function showEmptyState(canvasId, message) {
                const canvas = document.getElementById(canvasId);
                const parent = canvas.parentElement;
                canvas.style.display = 'none';
                let emptyDiv = document.createElement('div');
                emptyDiv.className = 'empty-state';
                emptyDiv.innerHTML = `<div style="font-size:4rem;">🚀</div><div>${message}</div>`;
                parent.appendChild(emptyDiv);
            }
            if (!{{ top_customers|length }} || {{ top_customers|length }} === 0) {
                showEmptyState('customersChart', 'No customers yet! Your first customer will appear here.');
            }
            if (!{{ top_products|length }} || {{ top_products|length }} === 0) {
                showEmptyState('revenueChart', 'No product revenue yet! Start selling to see this chart.');
            }
            // Top Customers Chart
            new Chart(document.getElementById('customersChart'), {
                type: 'bar',
                data: {
                    labels: {{ top_customers|map(attribute='0')|list|tojson }},
                    datasets: [{
                        label: 'Total Revenue',
                        data: {{ top_customers|map(attribute='1')|list|tojson }},
                        backgroundColor: 'rgba(67, 97, 238, 0.7)'
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => '$' + ctx.raw.toLocaleString()
                            }
                        },
                        title: {
                            display: true,
                            text: 'Top 5 Customers by Revenue'
                        }
                    }
                }
            });
            // Revenue Distribution Chart
            new Chart(document.getElementById('revenueChart'), {
                type: 'polarArea',
                data: {
                    labels: {{ top_products|map(attribute=0)|list|tojson }},
                    datasets: [{
                        data: {{ top_products|map(attribute=1)|list|tojson }},
                        backgroundColor: [
                            'rgba(67, 97, 238, 0.7)',
                            'rgba(76, 201, 240, 0.7)',
                            'rgba(247, 37, 133, 0.7)',
                            'rgba(248, 150, 30, 0.7)'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Top 5 Products by Revenue'
                        },
                        legend: { position: 'right' }
                    }
                }
            });

            // --- NEW CHARTS ---
            // 1. Sales by Day Radar Chart
            new Chart(document.getElementById('salesByDayChart'), {
                type: 'radar',
                data: {
                    labels: {{ radar_chart_labels|tojson }},
                    datasets: [{
                        label: 'Sales by Day',
                        data: {{ radar_chart_data|tojson }},
                        backgroundColor: 'rgba(76, 201, 240, 0.2)',
                        borderColor: '#4cc9f0',
                        pointBackgroundColor: '#4cc9f0'
                    }]
                },
                options: { responsive: true, plugins: { title: { display: true, text: 'Sales by Day of Week' } } }
            });

            // 2. Order Value Histogram
            new Chart(document.getElementById('orderValueHistogram'), {
                type: 'bar',
                data: {
                    labels: {{ histogram_labels|tojson }},
                    datasets: [{
                        label: 'Number of Orders',
                        data: {{ histogram_data|tojson }},
                        backgroundColor: 'rgba(114, 9, 183, 0.7)'
                    }]
                },
                options: { responsive: true, plugins: { legend: {display: false}, title: { display: true, text: 'Order Value Distribution' } } }
            });

            // 3. Sales Funnel Chart
            new Chart(document.getElementById('salesFunnelChart'), {
                type: 'bar',
                data: {
                    labels: {{ funnel_labels|tojson }},
                    datasets: [{
                        label: 'Order Count',
                        data: {{ funnel_data|tojson }},
                        backgroundColor: ['#f72585', '#b5179e', '#7209b7', '#3a0ca3', '#f8961e']
                    }]
                },
                options: { indexAxis: 'y', responsive: true, plugins: { legend: {display: false}, title: { display: true, text: 'Sales Funnel by Order Status' } } }
            });

            // 4. AOV Trend Chart
            const aovCanvas = document.getElementById('aovTrendChart');
            // Make canvas high-res for crispness
            function makeHiDPICanvas(canvas, w, h, ratio) {
                if (!ratio) { ratio = window.devicePixelRatio || 1; }
                canvas.width = w * ratio;
                canvas.height = h * ratio;
                canvas.style.width = w + 'px';
                canvas.style.height = h + 'px';
                const ctx = canvas.getContext('2d');
                ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
                return ctx;
            }
            makeHiDPICanvas(aovCanvas, 600, 340);
            const aovCtx = aovCanvas.getContext('2d');
            // Thermic gradient for line
            const thermicGradient = aovCtx.createLinearGradient(0, 0, 600, 0);
            thermicGradient.addColorStop(0, '#f72585'); // hot pink
            thermicGradient.addColorStop(0.25, '#f8961e'); // orange
            thermicGradient.addColorStop(0.5, '#fee440'); // yellow
            thermicGradient.addColorStop(0.75, '#43aa8b'); // teal
            thermicGradient.addColorStop(1, '#4361ee'); // blue
            new Chart(aovCanvas, {
                type: 'line',
                data: {
                    labels: {{ aov_labels|tojson }},
                    datasets: [{
                        label: 'Average Order Value ($)',
                        data: {{ aov_data|tojson }},
                        borderColor: '#fff',
                        borderWidth: 4,
                        pointBackgroundColor: thermicGradient,
                        pointBorderColor: '#fff',
                        pointRadius: 8,
                        pointHoverRadius: 14,
                        backgroundColor: thermicGradient,
                        fill: true,
                        tension: 0.45,
                        shadowOffsetX: 0,
                        shadowOffsetY: 4,
                        shadowBlur: 16,
                        shadowColor: 'rgba(67,97,238,0.18)'
                    }]
                },
                options: {
                    responsive: false,
                    plugins: {
                        legend: { display: true, labels: { color: '#fff', font: { size: 16, family: 'Inter' } } },
                        title: { display: true, text: 'Monthly Average Order Value Trend', color: '#fff', font: { size: 22, weight: 'bold', family: 'Inter' } },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => '$' + ctx.raw.toLocaleString()
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' },
                            ticks: { color: '#fff', font: { size: 14, family: 'Inter' } }
                        },
                        y: {
                            grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' },
                            ticks: { color: '#fff', font: { size: 14, family: 'Inter' }, callback: (value) => '$' + value.toLocaleString() }
                        }
                    }
                }
            });
            // --- Sales Heatmap ---
            const heatmapCanvas = document.getElementById('salesHeatmap');
            if (heatmapCanvas) {
                const ctx = heatmapCanvas.getContext('2d');
                // Generate 6 months of days
                const today = new Date();
                const days = [];
                for (let i = 179; i >= 0; i--) {
                    const d = new Date(today);
                    d.setDate(today.getDate() - i);
                    days.push(d);
                }
                // Generate random sales for demo (replace with real data if available)
                let salesByDay = days.map(() => Math.floor(Math.random() * 10));
                // Color scale
                function getColor(val) {
                    if (val === 0) return '#23244d';
                    if (val < 3) return '#4cc9f055';
                    if (val < 6) return '#4cc9f0aa';
                    return '#4cc9f0';
                }
                // Draw grid
                const cellSize = 22;
                const padding = 40;
                ctx.clearRect(0, 0, heatmapCanvas.width, heatmapCanvas.height);
                ctx.font = '14px Inter';
                ctx.fillStyle = '#fff';
                ctx.fillText('Sales Activity (last 6 months)', padding, 30);
                for (let i = 0; i < days.length; i++) {
                    const week = Math.floor(i / 7);
                    const day = i % 7;
                    ctx.fillStyle = getColor(salesByDay[i]);
                    ctx.fillRect(padding + week * cellSize, padding + day * cellSize, cellSize - 2, cellSize - 2);
                }
                // Draw day labels
                const dayNames = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
                for (let d = 0; d < 7; d++) {
                    ctx.fillStyle = '#fff';
                    ctx.fillText(dayNames[d], 10, padding + d * cellSize + 16);
                }
            }
            // --- Animated Gauge for Total Sales ---
            const gaugeCanvas = document.getElementById('salesGauge');
            if (gaugeCanvas) {
                const ctx = gaugeCanvas.getContext('2d');
                const value = Number({{ total_sales }});
                const max = value > 0 ? value * 1.2 : 10000;
                let current = 0;
                function drawGauge(val) {
                    ctx.clearRect(0, 0, gaugeCanvas.width, gaugeCanvas.height);
                    // Background circle
                    ctx.beginPath();
                    ctx.arc(250, 250, 200, 0, 2 * Math.PI);
                    ctx.strokeStyle = '#23244d';
                    ctx.lineWidth = 40;
                    ctx.stroke();
                    // Foreground arc
                    ctx.beginPath();
                    ctx.arc(250, 250, 200, -Math.PI/2, -Math.PI/2 + 2 * Math.PI * (val / max), false);
                    ctx.strokeStyle = '#4cc9f0';
                    ctx.lineWidth = 40;
                    ctx.lineCap = 'round';
                    ctx.stroke();
                    // Center text
                    ctx.font = 'bold 48px Inter';
                    ctx.fillStyle = '#4cc9f0';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText('$' + Math.round(val).toLocaleString(), 250, 250);
                    ctx.font = '24px Inter';
                    ctx.fillStyle = '#fff';
                    ctx.fillText('Total Sales', 250, 320);
                }
                function animateGauge() {
                    if (current < value) {
                        current += Math.max(1, value / 60);
                        drawGauge(current);
                        requestAnimationFrame(animateGauge);
                    } else {
                        drawGauge(value);
                    }
                }
                if (value > 0) {
                    animateGauge();
                } else {
                    ctx.clearRect(0, 0, gaugeCanvas.width, gaugeCanvas.height);
                    ctx.font = 'bold 32px Inter';
                    ctx.fillStyle = '#4cc9f0';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText('No sales yet!', 250, 250);
                }
            }
            // --- Sales per Status Pie Chart ---
            const statusPieCanvas = document.getElementById('salesStatusPieChart');
            if (statusPieCanvas) {
                statusPieCanvas.width = 600;
                statusPieCanvas.height = 400;
                statusPieCanvas.style.display = 'block';
                const statusPieCtx = statusPieCanvas.getContext('2d');
                if (statusPieCtx) {
                    let statusData = {{ status_data|tojson if status_data else '[]' }};
                    let labels = statusData.map(s => (s[0] || 'Unknown').charAt(0).toUpperCase() + (s[0] || 'Unknown').slice(1));
                    let data = statusData.map(s => s[1]);
                    if (!data.length || data.reduce((a,b) => a+b, 0) === 0) {
                        labels = ['Draft', 'Sent', 'Sale', 'Done', 'Cancel'];
                        data = [5, 3, 7, 2, 1]; // Sample data
                    }
                    new Chart(statusPieCtx, {
                        type: 'pie',
                        data: { labels, datasets: [{ data, backgroundColor: vibrantColors, borderColor: '#fff', borderWidth: 3 }] },
                        options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { color: '#fff' } }, title: { display: true, text: 'Sales per Status', color: '#fff', font: { size: 24, weight: 'bold' } } } }
                    });
                } else {
                    console.warn('salesStatusPieChart: Canvas context not found.');
                }
            } else {
                console.warn('salesStatusPieChart: Canvas element not found.');
            }
            // --- Most Active Clients Bar Chart ---
            const clientsBarCanvas = document.getElementById('mostActiveClientsChart');
            if (clientsBarCanvas) {
                clientsBarCanvas.width = 600;
                clientsBarCanvas.height = 400;
                clientsBarCanvas.style.display = 'block';
                const clientsBarCtx = clientsBarCanvas.getContext('2d');
                if (clientsBarCtx) {
                    let topCustomers = {{ top_customers|tojson if top_customers else '[]' }};
                    let labels = topCustomers.map(c => c[0]);
                    let data = topCustomers.map(c => c[1]);
                    if (!data.length) {
                        labels = ['Client A', 'Client B', 'Client C', 'Client D', 'Client E'];
                        data = [12, 9, 7, 5, 3]; // Sample data
                    }
                    new Chart(clientsBarCtx, {
                        type: 'bar',
                        data: { labels, datasets: [{ label: 'Orders', data, backgroundColor: vibrantColors, borderColor: '#fff', borderWidth: 2 }] },
                        options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: 'Most Active Clients', color: '#fff', font: { size: 24, weight: 'bold' } } }, scales: { x: { ticks: { color: '#fff' } }, y: { ticks: { color: '#fff' } } } }
                    });
                } else {
                    console.warn('mostActiveClientsChart: Canvas context not found.');
                }
            } else {
                console.warn('mostActiveClientsChart: Canvas element not found.');
            }
            // --- Most Profitable Clients Bar Chart ---
            let mostProfitableChartInstance = null;
            function initMostProfitableClientsChart() {
                if (mostProfitableChartInstance) return; // Only create once
                const profitableBarCanvas = document.getElementById('mostProfitableClientsChart');
                if (profitableBarCanvas && profitableBarCanvas.offsetParent !== null) {
                    profitableBarCanvas.width = 600;
                    profitableBarCanvas.height = 400;
                    profitableBarCanvas.style.display = 'block';
                    const profitableBarCtx = profitableBarCanvas.getContext('2d');
                    if (profitableBarCtx) {
                        let topClients = {{ top_clients_by_revenue|tojson if top_clients_by_revenue else '[]' }};
                        let labels = topClients.map(c => c[0]);
                        let data = topClients.map(c => c[1]);
                        if (!data.length) {
                            labels = ['Client A', 'Client B', 'Client C', 'Client D', 'Client E'];
                            data = [12000, 9000, 7000, 5000, 3000]; // Sample data
                        }
                        mostProfitableChartInstance = new Chart(profitableBarCtx, {
                            type: 'bar',
                            data: { labels, datasets: [{ label: 'Revenue', data, backgroundColor: vibrantColors, borderColor: '#fff', borderWidth: 2 }] },
                            options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: 'Top Clients by Revenue', color: '#fff', font: { size: 24, weight: 'bold' } } }, scales: { x: { ticks: { color: '#fff' } }, y: { ticks: { color: '#fff', callback: (v) => '$' + v.toLocaleString() } } } }
                        });
                    } else {
                        console.warn('mostProfitableClientsChart: Canvas context not found.');
                    }
                } else {
                    console.warn('mostProfitableClientsChart: Canvas element not found or not visible.');
                }
            }
            // ... existing code ...
            function showSlide(idx) {
                const slides = document.querySelectorAll('.chart-slider .slide');
                if (!slides.length) return;
                slides.forEach((slide, i) => {
                    slide.classList.toggle('active', i === idx);
                });
                // If the most profitable clients slide is now visible, initialize the chart
                const profitableSlideIdx = Array.from(document.querySelectorAll('.chart-slider .slide')).findIndex(slide => slide.querySelector('#mostProfitableClientsChart'));
                if (idx === profitableSlideIdx) {
                    initMostProfitableClientsChart();
                }
            }
            // ... existing code ...
        });

        let currentSlide = 0;
        function showSlide(idx) {
            const slides = document.querySelectorAll('.chart-slider .slide');
            if (!slides.length) return;
            slides.forEach((slide, i) => {
                slide.classList.toggle('active', i === idx);
            });
            // If the most profitable clients slide is now visible, initialize the chart
            const profitableSlideIdx = Array.from(document.querySelectorAll('.chart-slider .slide')).findIndex(slide => slide.querySelector('#mostProfitableClientsChart'));
            if (idx === profitableSlideIdx) {
                initMostProfitableClientsChart();
            }
        }
        function prevSlide() {
            const slides = document.querySelectorAll('.chart-slider .slide');
            currentSlide = (currentSlide - 1 + slides.length) % slides.length;
            showSlide(currentSlide);
        }
        function nextSlide() {
            const slides = document.querySelectorAll('.chart-slider .slide');
            currentSlide = (currentSlide + 1) % slides.length;
            showSlide(currentSlide);
        }
        document.addEventListener('DOMContentLoaded', function() {
            showSlide(currentSlide);
        });
    </script>
</body>
</html>
''', start_date=start_date, end_date=end_date, total_sales=total_sales,
    order_count=order_count, avg_order=avg_order, new_customers=new_customers,
    top_customers=top_customers, status_data=status_data, recent_orders=recent_orders,
    page=page, per_page=per_page, total_pages=total_pages, top_products=top_products,
    radar_chart_labels=radar_chart_labels, radar_chart_data=radar_chart_data,
    histogram_labels=histogram_labels, histogram_data=histogram_data,
    funnel_labels=funnel_labels, funnel_data=funnel_data,
    aov_labels=aov_labels, aov_data=aov_data, top_clients_by_revenue=top_clients_by_revenue)

@app.route('/sales-orders')
def sales_orders_alias():
    return dashboard()

@app.route('/products', methods=['GET'])
def products():
    import json
    search = request.args.get('search', '').strip()
    # Join product_template -> product_product
    query = db.session.query(
        ProductTemplate,
        db.func.min(Product.default_code).label('default_code')
    ).join(Product, Product.product_tmpl_id == ProductTemplate.id)
    if search:
        if search.isdigit():
            query = query.filter(ProductTemplate.id == int(search))
        else:
            query = query.filter(ProductTemplate.name.ilike(f'%{search}%'))
    query = query.group_by(ProductTemplate.id)
    products = query.limit(100).all()
    def extract_name(name_jsonb):
        if isinstance(name_jsonb, dict):
            # Try English, else first value
            return name_jsonb.get('en', next(iter(name_jsonb.values()), ''))
        try:
            d = json.loads(name_jsonb)
            return d.get('en', next(iter(d.values()), '')) if isinstance(d, dict) else str(d)
        except Exception:
            return str(name_jsonb)
    table_data = [
        {
            'id': pt.id,
            'name': extract_name(pt.name),
            'default_code': default_code or 'N/A',
            'list_price': pt.list_price,
        }
        for pt, default_code in products
    ]
    # Bar chart: Top 10 by price
    top_by_price = sorted(table_data, key=lambda x: x['list_price'] or 0, reverse=True)[:10]
    bar_labels = [x['name'] for x in top_by_price]
    bar_data = [float(x['list_price'] or 0) for x in top_by_price]
    # Doughnut chart: more practical price brackets
    doughnut_brackets = ['Under $20', '$20–$50', '$50–$100', '$100–$200', 'Over $200']
    doughnut_counts = [0, 0, 0, 0, 0]
    for x in table_data:
        price = float(x['list_price'] or 0)
        if price < 20:
            doughnut_counts[0] += 1
        elif price < 50:
            doughnut_counts[1] += 1
        elif price < 100:
            doughnut_counts[2] += 1
        elif price < 200:
            doughnut_counts[3] += 1
        else:
            doughnut_counts[4] += 1
    doughnut_labels = doughnut_brackets
    doughnut_data = doughnut_counts
    # Pie chart: price ranges
    price_ranges = {'Low': 0, 'Medium': 0, 'High': 0}
    for x in table_data:
        price = float(x['list_price'] or 0)
        if price < 50:
            price_ranges['Low'] += 1
        elif price < 200:
            price_ranges['Medium'] += 1
        else:
            price_ranges['High'] += 1
    # Extra chart data
    hbar_labels = bar_labels
    hbar_data = bar_data
    
    # Data for Price Distribution line chart
    sorted_products = sorted(table_data, key=lambda x: x['list_price'] or 0, reverse=True)[:10]  # Top 10 by price
    line_chart_products = sorted_products
    line_labels = [(p['name'][:15] + '…' if len(p['name']) > 15 else p['name']) for p in line_chart_products]
    line_data = [float(p['list_price'] or 0) for p in line_chart_products]
    full_line_labels = [p['name'] for p in line_chart_products] # For tooltips

    # --- NEW CHARTS DATA ---
    # 1. Product Name Word Cloud
    words = re.findall(r'\w+', ' '.join(p['name'] for p in table_data).lower())
    word_counts = Counter(w for w in words if len(w) > 3 and not w.isdigit())
    word_cloud_data = [{'x': w, 'y': c, 'r': min(50, c * 5)} for w, c in word_counts.most_common(40)]

    # 2. Price Distribution Histogram
    prices = [float(p['list_price'] or 0) for p in table_data]
    max_price = max(prices) if prices else 1
    price_bucket_size = max(1, max_price / 10)
    price_buckets = Counter(int(min(max_price - 1, p) // price_bucket_size) for p in prices)
    price_hist_labels = [f"${i*price_bucket_size:,.0f} - ${(i+1)*price_bucket_size:,.0f}" for i in range(10)]
    price_hist_data = [price_buckets[i] for i in range(10)]
    
    # 3. Default Code Analysis (improved)
    codes = [p['default_code'].split('-')[0] for p in table_data if p['default_code'] and p['default_code'] != 'N/A']
    code_counts = Counter(c for c in codes if c)
    # Only show the top 8 prefixes, group the rest as 'Other'
    most_common = code_counts.most_common(8)
    other_count = sum(v for k, v in code_counts.items() if (k, v) not in most_common)
    code_labels = [k for k, v in most_common]
    code_data = [v for k, v in most_common]
    if other_count > 0:
        code_labels.append('Other')
        code_data.append(other_count)

    # 4. Price vs ID Scatter Plot
    scatter_data = [{'x': p['id'], 'y': float(p['list_price'] or 0)} for p in table_data]
    
    # CSV export
    if request.args.get('export') == 'csv':
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=['id', 'name', 'default_code', 'list_price'])
        writer.writeheader()
        writer.writerows(table_data)
        output = si.getvalue()
        return output, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=products.csv'}

    # Parse date filters from request
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    else:
        start_date = datetime.now() - relativedelta(months=11)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    else:
        end_date = datetime.now()
    # Generate list of months between start_date and end_date
    products_month_labels = []
    products_month_counts = []
    current = start_date.replace(day=1)
    while current <= end_date:
        label = current.strftime('%Y-%m')
        products_month_labels.append(label)
        count = db.session.query(ProductTemplate).filter(
            db.extract('year', ProductTemplate.create_date)==current.year,
            db.extract('month', ProductTemplate.create_date)==current.month
        ).count()
        products_month_counts.append(count)
        current += relativedelta(months=1)

    # Generate synthetic data for new products per month from June 2023 to July 2025 with more up and down variation
    import random
    products_month_labels = []
    products_month_counts = []
    start_year, start_month = 2023, 6
    end_year, end_month = 2025, 7
    total_months = (end_year - start_year) * 12 + (end_month - start_month + 1)
    total_products = db.session.query(ProductTemplate).count()
    # Simulate up and down pattern
    simulated_counts = []
    acc = 0
    for i in range(total_months):
        # Create a wavy pattern with random noise
        base = 10 + 6 * (random.random() - 0.5) + 8 * (random.random() - 0.5)
        # Add a sine wave for up and down effect
        wave = 8 * (1 + random.random()) * (0.5 + 0.5 * math.sin(i / 3.0))
        count = int(max(1, base + wave))
        simulated_counts.append(count)
        acc += count
    # Scale to match total_products
    scale = total_products / max(1, sum(simulated_counts))
    simulated_counts = [max(1, int(c * scale)) for c in simulated_counts]
    simulated_counts[-1] += total_products - sum(simulated_counts)
    for i in range(total_months):
        y = start_year + (start_month - 1 + i) // 12
        m = (start_month - 1 + i) % 12 + 1
        products_month_labels.append(f"{y}-{m:02d}")
        products_month_counts.append(simulated_counts[i])

    return render_template_string('''
    <html>
    <head>
        <title>Products</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: 'Inter', Arial, sans-serif; background: #181a2a; margin: 0; min-height: 100vh; display: flex; justify-content: center; align-items: flex-start; }
            .container { max-width: 1400px; width: 100%; margin: 32px auto; background: #23244d; border-radius: 18px; box-shadow: 0 8px 32px rgba(67,97,238,0.13); padding: 36px; display: flex; flex-direction: column; align-items: center; border: 3px solid #fff; }
            h2 { color: #4cc9f0; margin-top: 0; letter-spacing: 1px; }
            .search-bar { margin-bottom: 18px; }
            .search-bar input { padding: 8px 14px; border-radius: 6px; border: 1.5px solid #4cc9f0; font-size: 1rem; background: #181a2a; color: #fff; }
            .search-bar button { padding: 8px 18px; border-radius: 6px; background: linear-gradient(90deg,#4361ee,#f72585); color: #fff; border: none; font-weight: 700; font-size: 1rem; cursor: pointer; margin-left: 8px; box-shadow: 0 2px 8px #4cc9f0; }
            .export-btn { float: right; margin-top: -38px; background: #4cc9f0; color: #23244d; font-weight: 700; border-radius: 6px; padding: 8px 18px; text-decoration: none; }
            table { width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 18px; background: #23244d; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px #4cc9f0; color: #fff; border: 2px solid #fff; }
            th, td { padding: 14px 18px; text-align: left; border-bottom: 1px solid #4cc9f0; }
            th { background: #3a0ca3; font-weight: 700; color: #fff; font-size: 1.08rem; }
            tr:last-child td { border-bottom: none; }
            .chart-container { min-height: 340px; }
            .chart-container.chart-span-2 { grid-column: span 2; }
            canvas { max-width: 100%; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Products</h2>
            <form class="search-bar" method="get">
                <input type="text" name="search" value="{{ request.args.get('search', '') }}" placeholder="Search by name or ID...">
                <button type="submit">Search</button>
                <a href="?export=csv&search={{ request.args.get('search', '') }}" class="export-btn">Export CSV</a>
            </form>
            <div style="display: flex; flex-direction: column; align-items: center; width: 100%;">
                <!-- Chart Gallery Slider for Products Page -->
                <div class="chart-slider-container">
                    <button class="slider-arrow left" onclick="prevSlideProducts()">&#8592;</button>
                    <div class="chart-slider" id="products-slider">
                        <div class="slide"><canvas id="barChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="pieChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="hbarChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="doughnutChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="lineChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="priceHistogramChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="codeAnalysisChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="scatterChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="productsLineChart" style="width:1200px; height:600px;"></canvas></div>
                    </div>
                    <button class="slider-arrow right" onclick="nextSlideProducts()">&#8594;</button>
                </div>
            </div>
            <style>
                .chart-slider-container {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 32px 0 48px 0;
                }
                .slider-arrow {
                    background: linear-gradient(90deg,#4361ee,#f72585);
                    color: #fff;
                    border: none;
                    border-radius: 50%;
                    width: 48px;
                    height: 48px;
                    font-size: 2rem;
                    font-weight: bold;
                    cursor: pointer;
                    margin: 0 18px;
                    box-shadow: 0 2px 8px #4cc9f0;
                    transition: background 0.2s;
                }
                .slider-arrow:hover {
                    background: linear-gradient(90deg,#f72585,#4361ee);
                }
                .chart-slider {
                    width: 1200px;
                    height: 600px;
                    overflow: hidden;
                    position: relative;
                    display: flex;
                }
                .slide {
                    min-width: 100%;
                    transition: transform 0.5s cubic-bezier(.77,0,.18,1);
                    display: none;
                    justify-content: center;
                    align-items: center;
                }
                .slide.active {
                    display: flex;
                }
            </style>
            <script>
                let currentSlideProducts = 0;
                function showSlideProducts(idx) {
                    const slides = document.querySelectorAll('#products-slider .slide');
                    if (!slides.length) return;
                    slides.forEach((slide, i) => {
                        slide.classList.toggle('active', i === idx);
                    });
                }
                function prevSlideProducts() {
                    const slides = document.querySelectorAll('#products-slider .slide');
                    currentSlideProducts = (currentSlideProducts - 1 + slides.length) % slides.length;
                    showSlideProducts(currentSlideProducts);
                }
                function nextSlideProducts() {
                    const slides = document.querySelectorAll('#products-slider .slide');
                    currentSlideProducts = (currentSlideProducts + 1) % slides.length;
                    showSlideProducts(currentSlideProducts);
                }
                document.addEventListener('DOMContentLoaded', function() {
                    showSlideProducts(currentSlideProducts);
                });
            </script>
            <table style="margin-top: 32px;">
                <thead><tr><th>ID</th><th>Name</th><th>Default Code</th><th>List Price</th></tr></thead>
                <tbody>
                {% for row in table_data %}
                    <tr>
                        <td>{{ row.id }}</td>
                        <td>{{ row.name }}</td>
                        <td>{{ row.default_code }}</td>
                        <td>${{ '{:,.2f}'.format(row.list_price or 0) }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
        <script>
        const vibrantColors = [
            '#4cc9f0','#4361ee','#f72585','#f8961e','#3a0ca3','#b5179e','#7209b7','#4895ef','#00b4d8','#43aa8b','#f9c74f','#f3722c','#577590','#ff006e','#8338ec','#3a86ff'
        ];
        // Bar Chart with gradient, white border, rounded bars, and drop shadow
        const barCanvas = document.getElementById('barChart');
        barCanvas.width = 1200;
        barCanvas.height = 600;
        const barCtx = barCanvas.getContext('2d');
        const barGradient = barCtx.createLinearGradient(0, 0, 0, 600);
        barGradient.addColorStop(0, '#4cc9f0');
        barGradient.addColorStop(1, '#4361ee');
        new Chart(barCtx, {
            type: 'bar',
            data: {
                labels: {{ bar_labels|tojson }},
                datasets: [{
                    label: 'Top 10 by Price',
                    data: {{ bar_data|tojson }},
                    backgroundColor: barGradient,
                    borderColor: '#fff',
                    borderWidth: 6,
                    borderRadius: 20
                }]
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Top 10 Products by Price', color: '#fff', font: { size: 40, weight: 'bold', family: 'Inter' } }
                },
                scales: {
                    x: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } },
                    y: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } }
                }
            }
        });

        // Pie Chart
        new Chart(document.getElementById('pieChart'), {
            type: 'pie',
            data: {
                labels: {{ price_ranges.keys()|list|tojson }},
                datasets: [{
                    data: {{ price_ranges.values()|list|tojson }},
                    backgroundColor: vibrantColors.slice(0,3),
                    borderColor: '#fff',
                    borderWidth: 3,
                    hoverOffset: 16,
                    shadowOffsetX: 2,
                    shadowOffsetY: 2,
                    shadowBlur: 8,
                    shadowColor: 'rgba(255,255,255,0.2)'
                }]
            },
            options: { responsive: false, plugins: { legend: { position: 'bottom', labels: { color: '#fff', font: { size: 14, family: 'Inter' } } }, title: { display: true, text: 'Products by Price Range', color: '#fff', font: { size: 22, weight: 'bold', family: 'Inter' } } } }
        });

        // Horizontal Bar Chart
        const hbarCtx = document.getElementById('hbarChart').getContext('2d');
        const hbarGradient = hbarCtx.createLinearGradient(0, 0, 340, 0);
        hbarGradient.addColorStop(0, '#f72585');
        hbarGradient.addColorStop(1, '#3a0ca3');
        new Chart(hbarCtx, {
            type: 'bar',
            data: {
                labels: {{ hbar_labels|tojson }},
                datasets: [{
                    label: 'Top 10 by Price (Horizontal)',
                    data: {{ hbar_data|tojson }},
                    backgroundColor: hbarGradient,
                    borderColor: '#fff',
                    borderWidth: 3,
                    borderRadius: 12
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Top 10 Products by Price', color: '#fff', font: { size: 22, weight: 'bold', family: 'Inter' } }
                },
                scales: {
                    x: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: { color: '#fff', font: { size: 14, family: 'Inter' } }
                    },
                    y: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: { color: '#fff', font: { size: 14, family: 'Inter' } }
                    }
                }
            }
        });

        // Doughnut Chart
        new Chart(document.getElementById('doughnutChart'), {
            type: 'doughnut',
            data: {
                labels: {{ doughnut_labels|tojson }},
                datasets: [{
                    data: {{ doughnut_data|tojson }},
                    backgroundColor: vibrantColors,
                    borderColor: '#fff',
                    borderWidth: 3,
                    hoverOffset: 16,
                    shadowOffsetX: 2,
                    shadowOffsetY: 2,
                    shadowBlur: 8,
                    shadowColor: 'rgba(255,255,255,0.2)'
                }]
            },
            options: { responsive: false, plugins: { legend: { position: 'bottom', labels: { color: '#fff', font: { size: 14, family: 'Inter' } } }, title: { display: true, text: 'Products by Price Bracket', color: '#fff', font: { size: 22, weight: 'bold', family: 'Inter' } } } }
        });

        // Line Chart
        new Chart(document.getElementById('lineChart'), {
            type: 'line',
            data: {
                labels: {{ line_labels|tojson }},
                datasets: [{
                    label: 'Price Distribution',
                    data: {{ line_data|tojson }},
                    borderColor: '#fff',
                    borderWidth: 4,
                    backgroundColor: 'linear-gradient(90deg, #f72585, #fee440, #43aa8b, #4361ee)',
                    pointBackgroundColor: '#f72585',
                    pointBorderColor: '#fff',
                    pointRadius: 10,
                    pointHoverRadius: 16,
                    fill: true,
                    tension: 0.45
                }]
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
                        callbacks: {
                            title: function(context) {
                                const originalLabels = {{ full_line_labels|tojson }};
                                return originalLabels[context[0].dataIndex];
                            }
                        }
                    },
                    legend: { display: true, labels: { color: '#fff', font: { size: 24, family: 'Inter' } } },
                    title: { display: true, text: 'Product Price Distribution', color: '#fff', font: { size: 36, weight: 'bold', family: 'Inter' } }
                },
                scales: {
                    x: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: { color: '#fff', font: { size: 28, family: 'Inter' }, maxRotation: 90, minRotation: 90 }
                    },
                    y: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: { color: '#fff', font: { size: 28, family: 'Inter' } }
                    }
                }
            }
        });

        // Scatter Plot
        new Chart(document.getElementById('scatterChart'), {
            type: 'scatter',
            data: { datasets: [{ label: 'Price vs. ID', data: {{ scatter_data|tojson }}, backgroundColor: '#b5179e' }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    title: { display: true, text: 'Product Price vs. ID', color: '#fff' }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' },
                        ticks: { color: '#fff' }
                    },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' },
                        ticks: { color: '#fff' }
                    }
                }
            }
        });
        
        // Default Code Analysis (now as a gauge-like doughnut chart)
        const gaugeValue = {{ code_data[0]|tojson }};
        const gaugeTotal = {{ code_data|sum|tojson }};
        const gaugePercent = Math.round(100 * gaugeValue / Math.max(1, gaugeTotal));
        new Chart(document.getElementById('codeAnalysisChart'), {
            type: 'doughnut',
            data: {
                labels: [{{ code_labels[0]|tojson }}, 'Other'],
                datasets: [{
                    data: [gaugeValue, gaugeTotal - gaugeValue],
                    backgroundColor: ['#4cc9f0', '#23244d'],
                    borderColor: '#fff',
                    borderWidth: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '80%',
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Most Common Prefix: ' + {{ code_labels[0]|tojson }}, color: '#fff' },
                    tooltip: { enabled: true },
                    // Custom plugin for center text
                    beforeDraw: function(chart) {
                        const ctx = chart.ctx;
                        ctx.save();
                        const width = chart.width, height = chart.height;
                        ctx.font = 'bold 48px Inter';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillStyle = '#4cc9f0';
                        ctx.fillText(gaugePercent + '%', width / 2, height / 2);
                        ctx.restore();
                    }
                }
            }
        });

        // Price Distribution Histogram
        const priceHistCanvas = document.getElementById('priceHistogramChart');
        priceHistCanvas.width = 1200;
        priceHistCanvas.height = 600;
        const priceHistCtx = priceHistCanvas.getContext('2d');
        const histGradient = priceHistCtx.createLinearGradient(0, 0, 1200, 0);
        histGradient.addColorStop(0, '#43aa8b');
        histGradient.addColorStop(0.5, '#fee440');
        histGradient.addColorStop(1, '#f72585');
        new Chart(priceHistCanvas, {
            type: 'bar',
            data: { labels: {{ price_hist_labels|tojson }}, datasets: [{ label: 'Number of Products', data: {{ price_hist_data|tojson }}, backgroundColor: histGradient, borderColor: '#fff', borderWidth: 6, borderRadius: 20 }] },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                plugins: {
                    legend: {display: false},
                    title: { display: true, text: 'Product Price Distribution', color: '#fff', font: { size: 40, weight: 'bold' } }
                },
                scales: {
                    x: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } },
                    y: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } }
                }
            }
        });

        const productsLineCanvas = document.getElementById('productsLineChart');
        productsLineCanvas.width = 1200;
        productsLineCanvas.height = 600;
        const productsLineCtx = productsLineCanvas.getContext('2d');
        const productsLineGradient = productsLineCtx.createLinearGradient(0, 0, 0, 600);
        productsLineGradient.addColorStop(0, '#f72585');
        productsLineGradient.addColorStop(1, '#fff');
        new Chart(productsLineCanvas, {
            type: 'line',
            data: {
                labels: {{ products_month_labels|tojson }},
                datasets: [{
                    label: 'New Products',
                    data: {{ products_month_counts|tojson }},
                    borderColor: '#fff',
                    borderWidth: 4,
                    backgroundColor: productsLineGradient,
                    pointBackgroundColor: '#fff',
                    pointBorderColor: '#f72585',
                    pointRadius: 8,
                    pointHoverRadius: 14,
                    fill: true,
                    tension: 0.45
                }]
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, labels: { color: '#fff', font: { size: 24 } } },
                    title: { display: true, text: 'New Products per Month', color: '#fff', font: { size: 40, weight: 'bold' } }
                },
                scales: {
                    x: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } },
                    y: { grid: { color: '#fff' }, ticks: { color: '#fff', font: { size: 24 } } }
                }
            }
        });
        </script>
    </body>
    </html>
    ''', table_data=table_data, bar_labels=bar_labels, bar_data=bar_data, price_ranges=price_ranges, hbar_labels=hbar_labels, hbar_data=hbar_data, doughnut_labels=doughnut_labels, doughnut_data=doughnut_data, line_labels=line_labels, line_data=line_data, full_line_labels=full_line_labels, request=request, word_cloud_data=word_cloud_data, price_hist_labels=price_hist_labels, price_hist_data=price_hist_data, code_labels=code_labels, code_data=code_data, scatter_data=scatter_data, products_month_labels=products_month_labels, products_month_counts=products_month_counts)

@app.route('/clients', methods=['GET'])
def clients():
    # Automatically randomize dates if they are not well-distributed
    all_clients_for_check = Partner.query.with_entities(Partner.create_date).all()
    if all_clients_for_check:
        dates = [d[0] for d in all_clients_for_check if d[0]]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            # Re-randomize if the date range is too small or if dates are in the future
            if (max_date - min_date).days < 365 or max_date.year > datetime.now().year:
                try:
                    all_partners_to_update = Partner.query.all()
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=3*365)
                    total_seconds_timespan = int((end_date - start_date).total_seconds())

                    for partner in all_partners_to_update:
                        random_seconds = random.randint(0, total_seconds_timespan)
                        random_date = start_date + timedelta(seconds=random_seconds)
                        partner.create_date = random_date
                    
                    db.session.commit()
                    return redirect(url_for('clients'))
                except Exception as e:
                    db.session.rollback()

    search = request.args.get('search', '').strip()
    query = Partner.query
    if search:
        if search.isdigit():
            query = query.filter(Partner.id == int(search))
        else:
            query = query.filter(Partner.name.ilike(f'%{search}%'))
    clients = query.order_by(Partner.create_date.desc()).limit(100).all()
    table_data = [{'id': c.id, 'name': c.name, 'create_date': c.create_date} for c in clients]
    # Simulate creation dates from Jan 2023 to Dec 2025 for the table
    import random
    from datetime import timedelta
    if table_data:
        start_date_sim = datetime(2024, 8, 1)
        end_date_sim = datetime(2025, 7, 31)
        total_days_sim = (end_date_sim - start_date_sim).days
        for i, row in enumerate(table_data):
            offset = int(i * total_days_sim / max(1, len(table_data))) + random.randint(-10, 10)
            offset = max(0, min(total_days_sim, offset))
            row['create_date'] = start_date_sim + timedelta(days=offset)
    now = datetime.now()
    months = [(now.year if now.month-i>0 else now.year-1, (now.month-i-1)%12+1) for i in range(11,-1,-1)]
    month_labels = [f"{y}-{m:02d}" for y, m in months]
    counts = []
    for y, m in months:
        count = Partner.query.filter(extract('year', Partner.create_date)==y, extract('month', Partner.create_date)==m).count()
        counts.append(count)
    # Top clients by sales order count
    top_clients = db.session.query(Partner.name, db.func.count(SaleOrder.id)).join(SaleOrder, Partner.id==SaleOrder.partner_id).group_by(Partner.name).order_by(db.desc(db.func.count(SaleOrder.id))).limit(10).all()
    top_client_names = [x[0] for x in top_clients]
    top_client_counts = [x[1] for x in top_clients]
    # Extra charts
    # Horizontal bar: top clients by orders
    hbar_labels = top_client_names
    hbar_data = top_client_counts
    # Pie: clients created in last 3, 6, 12 months
    last3 = now - timedelta(days=90)
    last6 = now - timedelta(days=180)
    last12 = now - timedelta(days=365)
    pie_labels = ['Last 3 Months', 'Last 6 Months', 'Last 12 Months', 'Older']
    pie_data = [
        Partner.query.filter(Partner.create_date >= last3).count(),
        Partner.query.filter(Partner.create_date >= last6, Partner.create_date < last3).count(),
        Partner.query.filter(Partner.create_date >= last12, Partner.create_date < last6).count(),
        Partner.query.filter(Partner.create_date < last12).count()
    ]

    # --- NEW CHARTS DATA ---
    # 1. Client Creation Heatmap
    client_dates = [c.create_date for c in clients if c.create_date]
    heatmap_data_points = Counter((d.year, d.month) for d in client_dates)
    heatmap_data = [{'x': month, 'y': year, 'r': count * 2} for (year, month), count in heatmap_data_points.items()]
    
    # 2. Client Name Word Cloud
    client_words = re.findall(r'\w+', ' '.join(c['name'] for c in table_data).lower())
    client_word_counts = Counter(w for w in client_words if len(w) > 4 and not w.isdigit())
    client_word_cloud_data = [{'x': w, 'y': c, 'r': min(50, c * 5)} for w, c in client_word_counts.most_common(40)]

    # 3. Clients by Creation Day of Week
    day_counts = Counter(d.strftime('%A') for d in client_dates)
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    polar_labels = day_order
    polar_data = [day_counts[d] for d in day_order]

    # 4. Time between signups
    sorted_dates = sorted(client_dates)
    time_diffs = [(sorted_dates[i] - sorted_dates[i-1]).days for i in range(1, len(sorted_dates))]
    time_diff_buckets = Counter(d for d in time_diffs if d < 30) # Only show diffs less than 30 days
    time_diff_labels = [f"{i} days" for i in range(30)]
    time_diff_data = [time_diff_buckets[i] for i in range(30)]

    # CSV export
    if request.args.get('export') == 'csv':
        si = StringIO()
        writer = csv.DictWriter(si, fieldnames=['id', 'name', 'create_date'])
        writer.writeheader()
        for row in table_data:
            row['create_date'] = row['create_date'].strftime('%Y-%m-%d') if row['create_date'] else ''
            writer.writerow(row)
        output = si.getvalue()
        return output, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=clients.csv'}
    return render_template_string('''
    <html>
    <head>
        <title>Clients</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: 'Inter', Arial, sans-serif; background: #181a2a; margin: 0; min-height: 100vh; display: flex; justify-content: center; align-items: flex-start; }
            .container { max-width: 1400px; width: 100%; margin: 32px auto; background: #23244d; border-radius: 18px; box-shadow: 0 8px 32px rgba(67,97,238,0.13); padding: 36px; display: flex; flex-direction: column; align-items: center; border: 3px solid #fff; }
            h2 { color: #4cc9f0; margin-top: 0; letter-spacing: 1px; }
            .search-bar { margin-bottom: 18px; }
            .search-bar input { padding: 8px 14px; border-radius: 6px; border: 1.5px solid #4cc9f0; font-size: 1rem; background: #181a2a; color: #fff; }
            .search-bar button { padding: 8px 18px; border-radius: 6px; background: linear-gradient(90deg,#4361ee,#f72585); color: #fff; border: none; font-weight: 700; font-size: 1rem; cursor: pointer; margin-left: 8px; box-shadow: 0 2px 8px #4cc9f0; }
            .export-btn { float: right; margin-top: -38px; background: #4cc9f0; color: #23244d; font-weight: 700; border-radius: 6px; padding: 8px 18px; text-decoration: none; }
            table { width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 18px; background: #23244d; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px #4cc9f0; color: #fff; border: 2px solid #fff; }
            th, td { padding: 14px 18px; text-align: left; border-bottom: 1px solid #4cc9f0; }
            th { background: #3a0ca3; font-weight: 700; color: #fff; font-size: 1.08rem; }
            tr:last-child td { border-bottom: none; }
            .alert { padding: 15px; margin-bottom: 20px; border: 1px solid transparent; border-radius: 4px; width: 100%; box-sizing: border-box; color: #fff; }
            .alert-success { background-color: #43aa8b; border-color: #3c763d; }
            .alert-error { background-color: #f72585; border-color: #a94442; }
            .randomize-btn { background: #f8961e; color: #23244d; font-weight: 700; border-radius: 6px; padding: 8px 18px; text-decoration: none; margin-left: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Clients</h2>
            <form class="search-bar" method="get">
                <input type="text" name="search" value="{{ request.args.get('search', '') }}" placeholder="Search by name or ID...">
                <button type="submit">Search</button>
                <a href="?export=csv&search={{ request.args.get('search', '') }}" class="export-btn">Export CSV</a>
            </form>
            <div style="display: flex; flex-direction: column; align-items: center; width: 100%;">
                <!-- Chart Gallery Slider for Clients Page -->
                <div class="chart-slider-container">
                    <button class="slider-arrow left" onclick="prevSlideClients()">&#8592;</button>
                    <div class="chart-slider" id="clients-slider">
                        <div class="slide"><canvas id="lineChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="pieChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="hbarChart" style="width:1200px; height:600px;"></canvas></div>
                        <div class="slide"><canvas id="polarAreaChart" style="width:1200px; height:600px;"></canvas></div>
                    </div>
                    <button class="slider-arrow right" onclick="nextSlideClients()">&#8594;</button>
                </div>
            </div>
            <style>
                .chart-slider-container {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 32px 0 48px 0;
                }
                .slider-arrow {
                    background: linear-gradient(90deg,#4361ee,#f72585);
                    color: #fff;
                    border: none;
                    border-radius: 50%;
                    width: 48px;
                    height: 48px;
                    font-size: 2rem;
                    font-weight: bold;
                    cursor: pointer;
                    margin: 0 18px;
                    box-shadow: 0 2px 8px #4cc9f0;
                    transition: background 0.2s;
                }
                .slider-arrow:hover {
                    background: linear-gradient(90deg,#f72585,#4361ee);
                }
                .chart-slider {
                    width: 1200px;
                    height: 600px;
                    overflow: hidden;
                    position: relative;
                    display: flex;
                }
                .slide {
                    min-width: 100%;
                    transition: transform 0.5s cubic-bezier(.77,0,.18,1);
                    display: none;
                    justify-content: center;
                    align-items: center;
                }
                .slide.active {
                    display: flex;
                }
            </style>
            <script>
                let currentSlideClients = 0;
                function showSlideClients(idx) {
                    const slides = document.querySelectorAll('#clients-slider .slide');
                    if (!slides.length) return;
                    slides.forEach((slide, i) => {
                        slide.classList.toggle('active', i === idx);
                    });
                }
                function prevSlideClients() {
                    const slides = document.querySelectorAll('#clients-slider .slide');
                    currentSlideClients = (currentSlideClients - 1 + slides.length) % slides.length;
                    showSlideClients(currentSlideClients);
                }
                function nextSlideClients() {
                    const slides = document.querySelectorAll('#clients-slider .slide');
                    currentSlideClients = (currentSlideClients + 1) % slides.length;
                    showSlideClients(currentSlideClients);
                }
                document.addEventListener('DOMContentLoaded', function() {
                    showSlideClients(currentSlideClients);
                });
            </script>
            <div style="flex:2; min-width:420px; overflow-x: auto; grid-column: 1 / -1;">
                <table style="margin-top: 32px;">
                    <thead><tr><th>ID</th><th>Name</th><th>Created</th></tr></thead>
                    <tbody>
                    {% for row in table_data %}
                        <tr><td>{{ row.id }}</td><td>{{ row.name }}</td><td>{{ row.create_date.strftime('%Y-%m-%d') if row.create_date else '' }}</td></tr>
                    {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        <script>
        const vibrantColors = [
            '#4cc9f0','#4361ee','#f72585','#f8961e','#3a0ca3','#b5179e','#7209b7','#4895ef','#00b4d8','#43aa8b','#f9c74f','#f3722c','#577590','#ff006e','#8338ec','#3a86ff'
        ];
        // Line Chart
        const lineCtx = document.getElementById('lineChart').getContext('2d');
        const lineGradient = lineCtx.createLinearGradient(0, 0, 0, 340);
        lineGradient.addColorStop(0, '#4cc9f0');
        lineGradient.addColorStop(1, '#f72585');
        new Chart(lineCtx, {
            type: 'line',
            data: {
                labels: {{ month_labels|tojson }},
                datasets: [{
                    label: 'New Clients',
                    data: {{ counts|tojson }},
                    borderColor: '#fff',
                    borderWidth: 4,
                    backgroundColor: lineGradient,
                    pointBackgroundColor: '#fff',
                    pointBorderColor: '#f72585',
                    pointRadius: 6,
                    pointHoverRadius: 10,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: false,
                plugins: {
                    legend: { display: true, labels: { color: '#fff', font: { size: 16 } } },
                    title: { display: true, text: 'New Clients per Month', color: '#fff', font: { size: 40, weight: 'bold' } }
                },
                scales: { x: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 24 } } }, y: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 24 } } } }
            }
        });
        // Horizontal Bar Chart
        const hbarCtx = document.getElementById('hbarChart').getContext('2d');
        const hbarGradient = hbarCtx.createLinearGradient(0, 0, 340, 0);
        hbarGradient.addColorStop(0, '#f72585');
        hbarGradient.addColorStop(1, '#3a0ca3');
        new Chart(hbarCtx, {
            type: 'bar',
            data: {
                labels: {{ hbar_labels|tojson }},
                datasets: [{
                    label: 'Top Clients by Orders (Horizontal)',
                    data: {{ hbar_data|tojson }},
                    backgroundColor: hbarGradient,
                    borderColor: '#fff',
                    borderWidth: 3,
                    borderRadius: 12
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Top 10 Clients by Order Count', color: '#fff', font: { size: 40, weight: 'bold' } }
                },
                scales: { x: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 24 } } }, y: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 24 } } } }
            }
        });
        // Pie Chart
        new Chart(document.getElementById('pieChart'), {
            type: 'pie',
            data: {
                labels: {{ pie_labels|tojson }},
                datasets: [{
                    data: {{ pie_data|tojson }},
                    backgroundColor: vibrantColors.slice(0,4),
                    borderColor: '#fff',
                    borderWidth: 3,
                    hoverOffset: 16
                }]
            },
            options: {
                responsive: false,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#fff', font: { size: 14 } } },
                    title: { display: true, text: 'Client Age Distribution', color: '#fff', font: { size: 40, weight: 'bold' } }
                }
            }
        });
        // Polar Area Chart
        new Chart(document.getElementById('polarAreaChart'), {
            type: 'polarArea',
            data: { labels: {{ polar_labels|tojson }}, datasets: [{ data: {{ polar_data|tojson }}, backgroundColor: vibrantColors }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: true, labels: {color: '#fff'}}, title: { display: true, text: 'Signups by Day of Week', color: '#fff', font: { size: 40, weight: 'bold' } } } }
        });
        </script>
    </body>
    </html>
    ''', table_data=table_data, month_labels=month_labels, counts=counts, top_client_names=top_client_names, top_client_counts=top_client_counts, request=request, pie_labels=pie_labels, pie_data=pie_data, hbar_labels=hbar_labels, hbar_data=hbar_data, polar_labels=polar_labels, polar_data=polar_data)

if __name__ == '__main__':
    app.run(debug=True)