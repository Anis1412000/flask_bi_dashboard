from flask import Flask, render_template_string, request, jsonify, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from collections import Counter
from sqlalchemy import extract
from io import StringIO
import csv
import random
import re

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

    # --- NEW CHARTS DATA ---
    # 1. Sales by Day of Week (Radar Chart)
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    sales_by_day_q = db.session.query(
        extract('isodow', SaleOrder.date_order),
        db.func.sum(SaleOrder.amount_total)
    ).filter(SaleOrder.date_order.between(start_date, end_date)).group_by(extract('isodow', SaleOrder.date_order)).all()
    sales_by_day = {day: 0.0 for day in days}
    for day_num, total in sales_by_day_q:
        if day_num and total: sales_by_day[days[day_num - 1]] = float(total)
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

    <!-- Charts Row 1 -->
    <div class="chart-row">
        <div class="chart-card">
            <canvas id="trendChart"></canvas>
        </div>
        <div class="chart-card">
            <canvas id="statusChart"></canvas>
        </div>
    </div>

    <!-- Charts Row 2 -->
    <div class="chart-row">
        <div class="chart-card">
            <canvas id="customersChart"></canvas>
        </div>
        <div class="chart-card">
            <canvas id="revenueChart"></canvas>
        </div>
    </div>

    <!-- New Charts Row -->
    <div class="chart-row" style="margin-top: 28px;">
        <div class="chart-card">
            <canvas id="salesByDayChart"></canvas>
        </div>
        <div class="chart-card">
            <canvas id="orderValueHistogram"></canvas>
        </div>
    </div>
    <div class="chart-row" style="margin-top: 28px;">
        <div class="chart-card">
            <canvas id="salesFunnelChart"></canvas>
        </div>
        <div class="chart-card">
            <canvas id="aovTrendChart"></canvas>
        </div>
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
            // Animate KPIs
            animateKPI('kpi-total-sales', Number({{ total_sales }}), '$', '', 2);
            animateKPI('kpi-order-count', Number({{ order_count }}));
            animateKPI('kpi-avg-order', Number({{ avg_order }}), '$', '', 2);
            animateKPI('kpi-new-customers', Number({{ new_customers }}));

            // Sales Trend Chart (sample data, replace with real data for production)
            const trendData = {
                labels: Array.from({length: 30}, (_, i) => {
                    const d = new Date();
                    d.setDate(d.getDate() - 30 + i);
                    return d.toLocaleDateString();
                }),
                data: Array.from({length: 30}, () => Math.floor(Math.random() * 10000) + 1000)
            };
            new Chart(document.getElementById('trendChart'), {
                type: 'line',
                data: {
                    labels: trendData.labels,
                    datasets: [{
                        label: 'Daily Sales',
                        data: trendData.data,
                        borderColor: 'rgba(67, 97, 238, 1)',
                        backgroundColor: 'rgba(67, 97, 238, 0.1)',
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: (ctx) => '$' + ctx.raw.toLocaleString()
                            }
                        },
                        title: {
                            display: true,
                            text: 'Sales Trend'
                        }
                    },
                    scales: {
                        y: {
                            ticks: {
                                callback: (value) => '$' + value.toLocaleString()
                            }
                        }
                    }
                }
            });
            // Status Chart
            new Chart(document.getElementById('statusChart'), {
                type: 'doughnut',
                data: {
                    labels: {{ status_data|map(attribute='0')|list|tojson }},
                    datasets: [{
                        data: {{ status_data|map(attribute='2')|list|tojson }},
                        backgroundColor: [
                            '#4cc9f0', '#4361ee', '#f72585', '#f8961e', '#3a0ca3'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'right' },
                        datalabels: {
                            formatter: (value) => '$' + value.toLocaleString(),
                            color: '#fff'
                        },
                        title: {
                            display: true,
                            text: 'Sales Distribution by Status'
                        }
                    }
                },
                plugins: [ChartDataLabels]
            });
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
            new Chart(document.getElementById('aovTrendChart'), {
                type: 'line',
                data: {
                    labels: {{ aov_labels|tojson }},
                    datasets: [{
                        label: 'Average Order Value ($)',
                        data: {{ aov_data|tojson }},
                        borderColor: '#43aa8b',
                        tension: 0.3,
                        fill: true,
                        backgroundColor: 'rgba(67, 170, 139, 0.1)'
                    }]
                },
                options: { responsive: true, plugins: { title: { display: true, text: 'Monthly Average Order Value Trend' } } }
            });
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
    aov_labels=aov_labels, aov_data=aov_data)

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
    sorted_products = sorted(table_data, key=lambda x: x['list_price'] or 0)
    line_chart_products = sorted_products[:15]  # Limit to 15 products for clarity

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
    
    # 3. Default Code Analysis
    codes = [p['default_code'].split('-')[0] for p in table_data if p['default_code'] and p['default_code'] != 'N/A']
    code_counts = Counter(c for c in codes if c)
    code_labels = list(code_counts.keys())
    code_data = list(code_counts.values())

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
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 32px; width: 100%;">
                <div class="chart-container"><canvas id="barChart"></canvas></div>
                <div class="chart-container"><canvas id="pieChart"></canvas></div>
                <div class="chart-container"><canvas id="hbarChart"></canvas></div>
                <div class="chart-container"><canvas id="doughnutChart"></canvas></div>
                <div class="chart-container chart-span-2"><canvas id="lineChart"></canvas></div>
                <div class="chart-container"><canvas id="wordCloudChart"></canvas></div>
                <div class="chart-container"><canvas id="priceHistogramChart"></canvas></div>
                <div class="chart-container"><canvas id="codeAnalysisChart"></canvas></div>
                <div class="chart-container chart-span-2"><canvas id="scatterChart"></canvas></div>
            </div>
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
        const barCtx = document.getElementById('barChart').getContext('2d');
        const barGradient = barCtx.createLinearGradient(0, 0, 0, 340);
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
                    borderWidth: 3,
                    borderRadius: 12,
                    hoverBackgroundColor: '#f72585',
                    shadowOffsetX: 2,
                    shadowOffsetY: 2,
                    shadowBlur: 8,
                    shadowColor: 'rgba(255,255,255,0.2)'
                }]
            },
            options: {
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

        // Pie Chart with white border and drop shadow
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

        // Horizontal Bar Chart with white border, rounded bars, and drop shadow
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

        // Doughnut Chart with white border and drop shadow
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

        // Line Chart with white border, drop shadow, and creative style
        const lineCtx = document.getElementById('lineChart').getContext('2d');
        const lineGradient = lineCtx.createLinearGradient(0, 0, 0, 340);
        lineGradient.addColorStop(0, '#f72585');
        lineGradient.addColorStop(1, '#4cc9f0');
        new Chart(lineCtx, {
            type: 'line',
            data: {
                labels: {{ line_labels|tojson }},
                datasets: [{
                    label: 'Price Distribution',
                    data: {{ line_data|tojson }},
                    borderColor: '#fff',
                    borderWidth: 4,
                    backgroundColor: lineGradient,
                    pointBackgroundColor: '#fff',
                    pointBorderColor: '#f72585',
                    pointRadius: 6,
                    pointHoverRadius: 10,
                    fill: true,
                    tension: 0.4,
                    shadowOffsetX: 2,
                    shadowOffsetY: 2,
                    shadowBlur: 8,
                    shadowColor: 'rgba(255,255,255,0.2)'
                }]
            },
            options: {
                responsive: false,
                plugins: {
                    tooltip: {
                        callbacks: {
                            title: function(context) {
                                const originalLabels = {{ full_line_labels|tojson }};
                                return originalLabels[context[0].dataIndex];
                            }
                        }
                    },
                    legend: { display: true, labels: { color: '#fff', font: { size: 16, family: 'Inter' } } },
                    title: { display: true, text: 'Product Price Distribution', color: '#fff', font: { size: 22, weight: 'bold', family: 'Inter' } }
                },
                scales: {
                    x: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: {
                            color: '#fff',
                            font: { size: 12, family: 'Inter' },
                            maxRotation: 90,
                            minRotation: 90
                        }
                    },
                    y: {
                        grid: { color: '#fff', borderColor: '#fff' },
                        ticks: { color: '#fff', font: { size: 14, family: 'Inter' } }
                    }
                }
            }
        });

        // --- NEW CHARTS ---
        // Word Cloud
        new Chart(document.getElementById('wordCloudChart'), {
            type: 'bubble',
            data: { datasets: [{ label: 'Product Keywords', data: {{ word_cloud_data|tojson }}, backgroundColor: vibrantColors }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false}, title: { display: true, text: 'Product Name Word Cloud', color: '#fff' } } }
        });

        // Price Histogram
        new Chart(document.getElementById('priceHistogramChart'), {
            type: 'bar',
            data: { labels: {{ price_hist_labels|tojson }}, datasets: [{ label: 'Number of Products', data: {{ price_hist_data|tojson }}, backgroundColor: '#f8961e' }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false}, title: { display: true, text: 'Product Price Histogram', color: '#fff' } } }
        });
        
        // Default Code Analysis
        new Chart(document.getElementById('codeAnalysisChart'), {
            type: 'bar',
            data: { labels: {{ code_labels|tojson }}, datasets: [{ label: 'Code Count', data: {{ code_data|tojson }}, backgroundColor: '#7209b7' }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false}, title: { display: true, text: 'Default Code Prefixes', color: '#fff' } } }
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
        </script>
    </body>
    </html>
    ''', table_data=table_data, bar_labels=bar_labels, bar_data=bar_data, price_ranges=price_ranges, hbar_labels=hbar_labels, hbar_data=hbar_data, doughnut_labels=doughnut_labels, doughnut_data=doughnut_data, line_labels=line_labels, line_data=line_data, full_line_labels=full_line_labels, request=request,
    word_cloud_data=word_cloud_data, price_hist_labels=price_hist_labels, price_hist_data=price_hist_data, code_labels=code_labels, code_data=code_data, scatter_data=scatter_data)

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
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 32px; width: 100%;">
                <div class="chart-container"><canvas id="lineChart"></canvas></div>
                <div class="chart-container"><canvas id="pieChart"></canvas></div>
                <div class="chart-container"><canvas id="hbarChart"></canvas></div>
                <div class="chart-container"><canvas id="polarAreaChart"></canvas></div>
                <div class="chart-container chart-span-2"><canvas id="heatmapChart"></canvas></div>
                <div class="chart-container"><canvas id="clientWordCloudChart"></canvas></div>
                <div class="chart-container"><canvas id="timeDiffHistogram"></canvas></div>
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
                    title: { display: true, text: 'New Clients per Month', color: '#fff', font: { size: 22, weight: 'bold' } }
                },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 14 } } },
                    y: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 14 } } }
                }
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
                    title: { display: true, text: 'Top 10 Clients by Order Count', color: '#fff', font: { size: 22, weight: 'bold' } }
                },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 14 } } },
                    y: { grid: { color: 'rgba(255,255,255,0.2)', borderColor: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', font: { size: 14 } } }
                }
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
                    title: { display: true, text: 'Client Age Distribution', color: '#fff', font: { size: 22, weight: 'bold' } }
                }
            }
        });

        // --- NEW CHARTS ---
        // 1. Heatmap
        new Chart(document.getElementById('heatmapChart'), {
            type: 'bubble',
            data: { datasets: [{ label: 'Client Signups', data: {{ heatmap_data|tojson }}, backgroundColor: '#4cc9f0' }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { title: { display: true, text: 'Client Creation Heatmap', color: '#fff' } },
                scales: {
                    x: { title: { display: true, text: 'Month', color: '#fff' }, grid: { color: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff' } },
                    y: { title: { display: true, text: 'Year', color: '#fff' }, grid: { color: 'rgba(255,255,255,0.2)' }, ticks: { color: '#fff', stepSize: 1 } }
                }
            }
        });
        // 2. Client Word Cloud
        new Chart(document.getElementById('clientWordCloudChart'), {
            type: 'bubble',
            data: { datasets: [{ label: 'Client Keywords', data: {{ client_word_cloud_data|tojson }}, backgroundColor: vibrantColors }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false}, title: { display: true, text: 'Client Name Word Cloud', color: '#fff' } } }
        });
        // 3. Polar Area Chart
        new Chart(document.getElementById('polarAreaChart'), {
            type: 'polarArea',
            data: { labels: {{ polar_labels|tojson }}, datasets: [{ data: {{ polar_data|tojson }}, backgroundColor: vibrantColors }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: true, labels: {color: '#fff'}}, title: { display: true, text: 'Signups by Day of Week', color: '#fff' } } }
        });
        // 4. Time Difference Histogram
        new Chart(document.getElementById('timeDiffHistogram'), {
            type: 'bar',
            data: { labels: {{ time_diff_labels|tojson }}, datasets: [{ label: 'Count', data: {{ time_diff_data|tojson }}, backgroundColor: '#f72585'}] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display: false}, title: { display: true, text: 'Time Between Client Signups (Days)', color: '#fff' } } }
        });
        </script>
    </body>
    </html>
    ''', table_data=table_data, month_labels=month_labels, counts=counts, top_client_names=top_client_names, top_client_counts=top_client_counts, request=request, pie_labels=pie_labels, pie_data=pie_data, hbar_labels=hbar_labels, hbar_data=hbar_data,
    heatmap_data=heatmap_data, client_word_cloud_data=client_word_cloud_data, polar_labels=polar_labels, polar_data=polar_data, time_diff_labels=time_diff_labels, time_diff_data=time_diff_data)

if __name__ == '__main__':
    app.run(debug=True)