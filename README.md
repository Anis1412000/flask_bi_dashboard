# 📊 Odoo Sales Dashboard

A comprehensive Flask-based dashboard for visualizing Odoo sales data with beautiful charts and analytics.

## ✨ Features

- **Interactive Dashboard** with real-time KPIs
- **Multiple Chart Types**: Line charts, bar charts, pie charts, radar charts, histograms
- **Advanced Analytics**: Sales trends, customer analysis, product insights
- **Date Filtering** for custom time periods
- **Responsive Design** that works on desktop and mobile
- **CSV Export** functionality
- **Multiple Views**: Sales Orders, Products, Clients

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- PostgreSQL database
- pip (Python package manager)

### Installation

1. **Install Dependencies**
   ```bash
   pip install --break-system-packages -r requirements.txt
   ```

2. **Configure Database**
   - Update database credentials in `app.py`:
   ```python
   app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://username:password@localhost/database_name'
   ```

3. **Run the Application**
   ```bash
   python3 run.py
   ```
   
   Or directly:
   ```bash
   python3 app.py
   ```

4. **Access Dashboard**
   - Open your browser and go to: `http://localhost:5000`

## 📱 Pages

- **Dashboard** (`/`) - Main analytics dashboard with KPIs and charts
- **Products** (`/products`) - Product catalog with pricing analysis
- **Clients** (`/clients`) - Customer management and analytics
- **Sales Orders** (`/sales-orders`) - Sales order management

## 🛠️ Configuration

### Database Setup

The application expects the following PostgreSQL tables:
- `public.sale_order` - Sales orders data
- `public.res_partner` - Customer/partner data
- `public.product_template` - Product templates
- `public.product_product` - Product variants
- `public.sale_order_line` - Sales order line items

### Environment Variables

You can also configure the database using environment variables:
```bash
export DATABASE_URL="postgresql://username:password@localhost/database_name"
```

## 🎨 Charts & Analytics

The dashboard includes:
- **Sales Trends** - Daily/monthly sales progression
- **Customer Analytics** - Top customers by revenue
- **Product Performance** - Best-selling products
- **Sales Funnel** - Order status distribution
- **Geographic Analysis** - Sales by region
- **Time-based Analysis** - Sales by day of week

## 🔧 Troubleshooting

### Common Issues

1. **ModuleNotFoundError: No module named 'flask'**
   ```bash
   pip install --break-system-packages flask flask-sqlalchemy psycopg2-binary
   ```

2. **Database Connection Error**
   - Verify PostgreSQL is running
   - Check database credentials in `app.py`
   - Ensure database exists

3. **Permission Denied**
   - Use `--break-system-packages` flag with pip
   - Or create a virtual environment

### Database Issues

If you get database connection errors:
1. Make sure PostgreSQL is running
2. Verify the database exists
3. Check username/password credentials
4. Ensure the database schema matches the expected format

## 📁 Project Structure

```
/workspace/
├── app.py              # Main Flask application
├── run.py              # Simple run script
├── requirements.txt    # Python dependencies
├── README.md          # This file
├── backend/
│   └── app.py         # Backend API (optional)
└── venv/              # Virtual environment (if used)
```

## 🎯 Next Steps

1. **Database Connection**: Set up your PostgreSQL database and update credentials
2. **Data Import**: Import your Odoo data into the expected table structure
3. **Customization**: Modify charts and KPIs to match your business needs
4. **Production**: Configure for production deployment with proper WSGI server

## 📝 Notes

- The application includes sample data generation for testing
- Charts are built with Chart.js for interactive visualization
- Responsive design works on desktop, tablet, and mobile
- Export functionality available for data analysis

## 🔒 Security

- Change the secret key in production
- Use environment variables for sensitive configuration
- Implement proper authentication for production use

---

**Enjoy your new dashboard! 📊✨**