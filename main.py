
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import sqlite3
import hashlib
import datetime
from decimal import Decimal
import os

app = Flask(__name__)
app.secret_key = 'seu_secret_key_aqui'

# Configuração do banco de dados
def init_db():
    conn = sqlite3.connect('loan_management.db')
    c = conn.cursor()
    
    # Verificar se as tabelas já existem
    tables_exist = c.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN ('users', 'organizations', 'user_billing')
    """).fetchall()
    
    # Se as tabelas principais não existem, criar todas
    if len(tables_exist) < 2:
        c.execute("DROP TABLE IF EXISTS payments")
        c.execute("DROP TABLE IF EXISTS loans") 
        c.execute("DROP TABLE IF EXISTS clients")
        c.execute("DROP TABLE IF EXISTS user_billing")
        c.execute("DROP TABLE IF EXISTS users")
        c.execute("DROP TABLE IF EXISTS organizations")
        
        # Tabela de organizações
        c.execute('''CREATE TABLE organizations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        # Tabela de usuários
        c.execute('''CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        role TEXT DEFAULT 'user',
                        organization_id INTEGER,
                        monthly_fee DECIMAL(10,2) DEFAULT 29.90,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (organization_id) REFERENCES organizations (id)
                    )''')
        
        # Tabela de clientes
        c.execute('''CREATE TABLE clients (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        document TEXT NOT NULL,
                        phone TEXT,
                        email TEXT,
                        address TEXT,
                        organization_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (organization_id) REFERENCES organizations (id),
                        UNIQUE(document, organization_id)
                    )''')
        
        # Tabela de empréstimos
        c.execute('''CREATE TABLE loans (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id INTEGER,
                        amount DECIMAL(10,2) NOT NULL,
                        interest_rate DECIMAL(5,2) NOT NULL,
                        loan_type TEXT NOT NULL,
                        installments INTEGER DEFAULT 1,
                        installment_amount DECIMAL(10,2),
                        total_amount DECIMAL(10,2),
                        loan_date DATE NOT NULL,
                        due_date DATE,
                        status TEXT DEFAULT 'active',
                        organization_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (client_id) REFERENCES clients (id),
                        FOREIGN KEY (organization_id) REFERENCES organizations (id)
                    )''')
        
        # Tabela de pagamentos
        c.execute('''CREATE TABLE payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        loan_id INTEGER,
                        amount DECIMAL(10,2) NOT NULL,
                        payment_type TEXT NOT NULL,
                        payment_date DATE NOT NULL,
                        notes TEXT,
                        organization_id INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (loan_id) REFERENCES loans (id),
                        FOREIGN KEY (organization_id) REFERENCES organizations (id)
                    )''')
    else:
        # Verificar se as colunas monthly_fee e start_date existem
        columns = c.execute("PRAGMA table_info(users)").fetchall()
        column_names = [column[1] for column in columns]
        if 'monthly_fee' not in column_names:
            c.execute('ALTER TABLE users ADD COLUMN monthly_fee DECIMAL(10,2) DEFAULT 29.90')
        if 'start_date' not in column_names:
            c.execute('ALTER TABLE users ADD COLUMN start_date DATE')
            c.execute("UPDATE users SET start_date = date('now') WHERE start_date IS NULL")
    
    # Verificar se a tabela de cobrança existe
    billing_exists = c.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_billing'
    """).fetchone()
    
    if not billing_exists:
        # Tabela de cobrança mensal
        c.execute('''CREATE TABLE user_billing (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        month_year TEXT NOT NULL,
                        amount DECIMAL(10,2) NOT NULL,
                        payment_date DATE,
                        status TEXT DEFAULT 'pending',
                        start_date DATE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (id),
                        UNIQUE(user_id, month_year)
                    )''')
    else:
        # Verificar se a coluna start_date existe
        columns = c.execute("PRAGMA table_info(user_billing)").fetchall()
        column_names = [column[1] for column in columns]
        if 'start_date' not in column_names:
            c.execute('ALTER TABLE user_billing ADD COLUMN start_date DATE')
    
    # Criar organização master se não existir (apenas na primeira criação)
    if len(tables_exist) < 2:
        c.execute('''INSERT INTO organizations (id, name) 
                     VALUES (0, 'Master Admin')''')
        
        # Criar usuário master Marina
        marina_password = hashlib.sha256('1316031119'.encode()).hexdigest()
        c.execute('''INSERT INTO users (username, password, role, organization_id) 
                     VALUES (?, ?, ?, ?)''', ('Marina', marina_password, 'master', 0))
    
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect('loan_management.db')
    conn.row_factory = sqlite3.Row
    return conn

# Função para inserir dados de exemplo apenas se necessário
def insert_sample_data():
    conn = get_db_connection()
    
    # Verificar se já existem dados
    existing_users = conn.execute('SELECT COUNT(*) as count FROM users WHERE role != "master"').fetchone()
    
    # Só inserir se não houver usuários (primeira execução)
    if existing_users['count'] == 0:
        # Criar organização master se não existir
        master_org = conn.execute('SELECT id FROM organizations WHERE id = 0').fetchone()
        if not master_org:
            conn.execute('''INSERT OR IGNORE INTO organizations (id, name) 
                           VALUES (0, 'Master Admin')''')
        
        # Criar usuário master Marina se não existir
        marina = conn.execute('SELECT id FROM users WHERE username = "Marina"').fetchone()
        if not marina:
            marina_password = hashlib.sha256('1316031119'.encode()).hexdigest()
            conn.execute('''INSERT OR IGNORE INTO users (username, password, role, organization_id) 
                           VALUES (?, ?, ?, ?)''', ('Marina', marina_password, 'master', 0))
    
    # Atualizar usuários existentes com valor de R$ 200 mensais se ainda estão com valor padrão
    conn.execute('''UPDATE users SET monthly_fee = 200.00 
                    WHERE role != 'master' AND (monthly_fee = 29.90 OR monthly_fee IS NULL)''')
    
    conn.commit()
    conn.close()

# Rotas de autenticação
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT u.*, o.name as org_name FROM users u LEFT JOIN organizations o ON u.organization_id = o.id WHERE u.username = ? AND u.password = ?',
            (username, password)
        ).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['organization_id'] = user['organization_id']
            session['org_name'] = user['org_name']
            
            if user['role'] == 'master':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos!')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Middleware para verificar autenticação
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Função para verificar se é master admin
def master_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'master':
            flash('Acesso negado!')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Função para filtrar por organização
def get_user_organization():
    return session.get('organization_id')

# Painel administrativo (apenas para Marina)
@app.route('/admin')
@master_required
def admin_panel():
    conn = get_db_connection()
    current_month = datetime.date.today().strftime('%Y-%m')
    
    # Buscar todas as organizações
    organizations = conn.execute('''
        SELECT o.*, COUNT(u.id) as user_count 
        FROM organizations o 
        LEFT JOIN users u ON o.id = u.organization_id 
        WHERE o.id > 0
        GROUP BY o.id 
        ORDER BY o.name
    ''').fetchall()
    
    # Buscar usuários com informações de cobrança
    users = conn.execute('''
        SELECT u.*, o.name as org_name,
               ub.status as payment_status,
               ub.payment_date as last_payment,
               CASE 
                   WHEN u.start_date <= date('now', 'start of month') THEN 'active'
                   ELSE 'future'
               END as billing_status
        FROM users u 
        JOIN organizations o ON u.organization_id = o.id 
        LEFT JOIN user_billing ub ON u.id = ub.user_id AND ub.month_year = ?
        WHERE u.role != 'master'
        ORDER BY o.name, u.username
    ''', (current_month,)).fetchall()
    
    # Calcular estatísticas
    monthly_revenue = conn.execute('''
        SELECT SUM(amount) as total 
        FROM user_billing 
        WHERE month_year = ? AND status = 'paid'
    ''', (current_month,)).fetchone()
    
    overdue_payments = conn.execute('''
        SELECT COUNT(*) as count 
        FROM user_billing 
        WHERE status = 'overdue'
    ''').fetchone()
    
    recent_payments = conn.execute('''
        SELECT ub.*, u.username, o.name as org_name
        FROM user_billing ub
        JOIN users u ON ub.user_id = u.id
        JOIN organizations o ON u.organization_id = o.id
        WHERE ub.status = 'paid'
        ORDER BY ub.payment_date DESC
        LIMIT 10
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin_panel.html', 
                         organizations=organizations, 
                         users=users,
                         monthly_revenue=float(monthly_revenue['total']) if monthly_revenue['total'] else 0,
                         overdue_payments=overdue_payments['count'],
                         recent_payments=recent_payments)

# Rotas de cobrança
@app.route('/admin/mark_payment_paid/<int:user_id>', methods=['POST'])
@master_required
def mark_payment_paid(user_id):
    current_month = datetime.date.today().strftime('%Y-%m')
    conn = get_db_connection()
    
    try:
        # Buscar valor mensal e data de início do usuário
        user = conn.execute('SELECT monthly_fee, start_date FROM users WHERE id = ?', (user_id,)).fetchone()
        
        # Verificar se o usuário deve ser cobrado neste mês
        if user['start_date']:
            start_date = datetime.datetime.strptime(user['start_date'], '%Y-%m-%d').date()
            current_month_date = datetime.date.today().replace(day=1)
            
            if start_date > current_month_date:
                return jsonify({'success': False, 'error': 'Usuário ainda não deve ser cobrado neste mês'})
        
        # Inserir ou atualizar cobrança
        conn.execute('''
            INSERT OR REPLACE INTO user_billing (user_id, month_year, amount, payment_date, status, start_date)
            VALUES (?, ?, ?, ?, 'paid', ?)
        ''', (user_id, current_month, user['monthly_fee'], datetime.date.today(), user['start_date']))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/admin/delete_user/<int:user_id>', methods=['DELETE'])
@master_required
def delete_user(user_id):
    conn = get_db_connection()
    try:
        # Excluir dados relacionados primeiro
        conn.execute('DELETE FROM user_billing WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM payments WHERE organization_id = (SELECT organization_id FROM users WHERE id = ?)', (user_id,))
        conn.execute('DELETE FROM loans WHERE organization_id = (SELECT organization_id FROM users WHERE id = ?)', (user_id,))
        conn.execute('DELETE FROM clients WHERE organization_id = (SELECT organization_id FROM users WHERE id = ?)', (user_id,))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/admin/update_user_fee/<int:user_id>', methods=['POST'])
@master_required
def update_user_fee(user_id):
    data = request.get_json()
    monthly_fee = data.get('monthly_fee')
    
    if not monthly_fee or monthly_fee <= 0:
        return jsonify({'success': False, 'error': 'Valor inválido'})
    
    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET monthly_fee = ? WHERE id = ?', (monthly_fee, user_id))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/admin/mark_all_payments_paid', methods=['POST'])
@master_required
def mark_all_payments_paid():
    current_month = datetime.date.today().strftime('%Y-%m')
    conn = get_db_connection()
    
    try:
        # Buscar usuários pendentes que devem ser cobrados
        users = conn.execute('''
            SELECT u.id, u.monthly_fee, u.start_date 
            FROM users u 
            LEFT JOIN user_billing ub ON u.id = ub.user_id AND ub.month_year = ?
            WHERE u.role != 'master' 
            AND (u.start_date IS NULL OR u.start_date <= date('now', 'start of month'))
            AND (ub.status IS NULL OR ub.status != 'paid')
        ''', (current_month,)).fetchall()
        
        # Marcar todos como pagos
        for user in users:
            conn.execute('''
                INSERT OR REPLACE INTO user_billing (user_id, month_year, amount, payment_date, status, start_date)
                VALUES (?, ?, ?, ?, 'paid', ?)
            ''', (user['id'], current_month, user['monthly_fee'], datetime.date.today(), user['start_date']))
        
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/admin/create_user', methods=['GET', 'POST'])
@master_required
def create_user():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        org_name = request.form['org_name']
        monthly_fee = float(request.form['monthly_fee'])
        start_date = datetime.datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        
        conn = get_db_connection()
        c = conn.cursor()
        try:
            # Criar organização se não existir
            org = conn.execute('SELECT id FROM organizations WHERE name = ?', (org_name,)).fetchone()
            if not org:
                c.execute('INSERT INTO organizations (name) VALUES (?)', (org_name,))
                org_id = c.lastrowid
            else:
                org_id = org['id']
            
            # Criar usuário
            c.execute('''
                INSERT INTO users (username, password, role, organization_id, monthly_fee, start_date)
                VALUES (?, ?, 'user', ?, ?, ?)
            ''', (username, password, org_id, monthly_fee, start_date))
            
            conn.commit()
            flash(f'Usuário {username} criado com sucesso! Valor mensal: R$ {monthly_fee:.2f}')
            return redirect(url_for('admin_panel'))
            
        except sqlite3.IntegrityError:
            flash('Nome de usuário já existe!')
        finally:
            conn.close()
    
    conn = get_db_connection()
    organizations = conn.execute('SELECT * FROM organizations WHERE id > 0 ORDER BY name').fetchall()
    conn.close()
    
    return render_template('create_user.html', organizations=organizations)

# Rotas principais
@app.route('/')
@login_required
def dashboard():
    # Verificar se é master admin
    if session.get('role') == 'master':
        return redirect(url_for('admin_panel'))
    
    org_id = get_user_organization()
    conn = get_db_connection()
    
    # Estatísticas do dashboard
    stats = {}
    
    # Total emprestado
    result = conn.execute('SELECT SUM(amount) as total FROM loans WHERE status = "active" AND organization_id = ?', (org_id,)).fetchone()
    stats['total_lent'] = float(result['total']) if result['total'] else 0
    
    # Total a receber
    result = conn.execute('SELECT SUM(total_amount) as total FROM loans WHERE status = "active" AND organization_id = ?', (org_id,)).fetchone()
    stats['total_to_receive'] = float(result['total']) if result['total'] else 0
    
    # Total recebido
    result = conn.execute('SELECT SUM(amount) as total FROM payments WHERE organization_id = ?', (org_id,)).fetchone()
    stats['total_received'] = float(result['total']) if result['total'] else 0
    
    # Clientes em atraso
    today = datetime.date.today()
    result = conn.execute('''SELECT COUNT(DISTINCT l.client_id) as count 
                            FROM loans l WHERE l.due_date < ? AND l.status = "active" AND l.organization_id = ?''', 
                         (today, org_id)).fetchone()
    stats['overdue_clients'] = result['count'] if result['count'] else 0
    
    # Próximos vencimentos (próximos 7 dias)
    next_week = today + datetime.timedelta(days=7)
    upcoming_loans = conn.execute('''
        SELECT l.*, c.full_name 
        FROM loans l 
        JOIN clients c ON l.client_id = c.id 
        WHERE l.due_date BETWEEN ? AND ? AND l.status = "active" AND l.organization_id = ?
        ORDER BY l.due_date
    ''', (today, next_week, org_id)).fetchall()
    
    # Empréstimos em atraso
    overdue_loans = conn.execute('''
        SELECT l.*, c.full_name 
        FROM loans l 
        JOIN clients c ON l.client_id = c.id 
        WHERE l.due_date < ? AND l.status = "active" AND l.organization_id = ?
        ORDER BY l.due_date
    ''', (today, org_id)).fetchall()
    
    conn.close()
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         upcoming_loans=upcoming_loans,
                         overdue_loans=overdue_loans)

@app.route('/clients')
@login_required
def clients():
    org_id = get_user_organization()
    conn = get_db_connection()
    clients = conn.execute('''
        SELECT c.*, 
               COUNT(l.id) as loan_count,
               SUM(CASE WHEN l.status = "active" THEN l.total_amount ELSE 0 END) as total_debt
        FROM clients c
        LEFT JOIN loans l ON c.id = l.client_id AND l.organization_id = ?
        WHERE c.organization_id = ?
        GROUP BY c.id
        ORDER BY c.full_name
    ''', (org_id, org_id)).fetchall()
    conn.close()
    
    return render_template('clients.html', clients=clients)

@app.route('/add_client', methods=['GET', 'POST'])
@login_required
def add_client():
    org_id = get_user_organization()
    if request.method == 'POST':
        conn = get_db_connection()
        try:
            conn.execute('''
                INSERT INTO clients (full_name, document, phone, email, address, organization_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                request.form['full_name'],
                request.form['document'],
                request.form['phone'],
                request.form['email'],
                request.form['address'],
                org_id
            ))
            conn.commit()
            flash('Cliente cadastrado com sucesso!')
            return redirect(url_for('clients'))
        except sqlite3.IntegrityError:
            flash('Documento já cadastrado nesta organização!')
        finally:
            conn.close()
    
    return render_template('add_client.html')

@app.route('/loans')
@login_required
def loans():
    org_id = get_user_organization()
    conn = get_db_connection()
    loans = conn.execute('''
        SELECT l.*, c.full_name, c.document,
               (l.total_amount - COALESCE(SUM(p.amount), 0)) as remaining_amount
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        LEFT JOIN payments p ON l.id = p.loan_id
        WHERE l.organization_id = ?
        GROUP BY l.id
        ORDER BY l.loan_date DESC
    ''', (org_id,)).fetchall()
    conn.close()
    
    # Converter para lista de dicionários para facilitar o processamento
    loans_list = []
    today = datetime.date.today()
    
    for loan in loans:
        loan_dict = dict(loan)
        # Determinar se está em atraso
        due_date = datetime.datetime.strptime(loan['due_date'], '%Y-%m-%d').date()
        if loan['status'] == 'active' and due_date < today:
            loan_dict['is_overdue'] = True
        else:
            loan_dict['is_overdue'] = False
        loans_list.append(loan_dict)
    
    return render_template('loans.html', loans=loans_list)

@app.route('/add_loan', methods=['GET', 'POST'])
@login_required
def add_loan():
    conn = get_db_connection()
    
    if request.method == 'POST':
        client_id = int(request.form['client_id'])
        amount = float(request.form['amount'])
        interest_rate = float(request.form['interest_rate'])
        loan_type = request.form['loan_type']
        loan_date = datetime.datetime.strptime(request.form['loan_date'], '%Y-%m-%d').date()
        
        # Calcular valores
        if loan_type == 'single':
            installments = 1
            total_amount = amount * (1 + interest_rate / 100)
            installment_amount = total_amount
            due_date = datetime.datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        else:
            installments = int(request.form['installments'])
            total_amount = amount * (1 + interest_rate / 100)
            installment_amount = total_amount / installments
            due_date = loan_date + datetime.timedelta(days=30)  # Primeira parcela
        
        org_id = get_user_organization()
        conn.execute('''
            INSERT INTO loans (client_id, amount, interest_rate, loan_type, 
                             installments, installment_amount, total_amount, 
                             loan_date, due_date, organization_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (client_id, amount, interest_rate, loan_type, 
              installments, installment_amount, total_amount, 
              loan_date, due_date, org_id))
        
        conn.commit()
        conn.close()
        flash('Empréstimo cadastrado com sucesso!')
        return redirect(url_for('loans'))
    
    org_id = get_user_organization()
    clients = conn.execute('SELECT * FROM clients WHERE organization_id = ? ORDER BY full_name', (org_id,)).fetchall()
    conn.close()
    
    return render_template('add_loan.html', clients=clients)

@app.route('/loan/<int:loan_id>')
@login_required
def loan_detail(loan_id):
    org_id = get_user_organization()
    conn = get_db_connection()
    
    loan = conn.execute('''
        SELECT l.*, c.full_name, c.document, c.phone, c.email
        FROM loans l
        JOIN clients c ON l.client_id = c.id
        WHERE l.id = ? AND l.organization_id = ?
    ''', (loan_id, org_id)).fetchone()
    
    payments = conn.execute('''
        SELECT * FROM payments 
        WHERE loan_id = ? 
        ORDER BY payment_date DESC
    ''', (loan_id,)).fetchall()
    
    total_paid = conn.execute('''
        SELECT SUM(amount) as total 
        FROM payments 
        WHERE loan_id = ?
    ''', (loan_id,)).fetchone()
    
    conn.close()
    
    if not loan:
        flash('Empréstimo não encontrado!')
        return redirect(url_for('loans'))
    
    remaining = float(loan['total_amount']) - (float(total_paid['total']) if total_paid['total'] else 0)
    
    # Verificar se está em atraso
    today = datetime.date.today()
    due_date = datetime.datetime.strptime(loan['due_date'], '%Y-%m-%d').date()
    is_overdue = loan['status'] == 'active' and due_date < today
    
    return render_template('loan_detail.html', 
                         loan=loan, 
                         payments=payments, 
                         total_paid=float(total_paid['total']) if total_paid['total'] else 0,
                         remaining=remaining,
                         is_overdue=is_overdue)

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/add_payment/<int:loan_id>', methods=['POST'])
@login_required
def add_payment(loan_id):
    org_id = get_user_organization()
    amount = float(request.form['amount'])
    payment_type = request.form['payment_type']
    payment_date = datetime.datetime.strptime(request.form['payment_date'], '%Y-%m-%d').date()
    notes = request.form.get('notes', '')
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO payments (loan_id, amount, payment_type, payment_date, notes, organization_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (loan_id, amount, payment_type, payment_date, notes, org_id))
    
    # Verificar se o empréstimo foi quitado
    loan = conn.execute('SELECT total_amount FROM loans WHERE id = ?', (loan_id,)).fetchone()
    total_paid = conn.execute('SELECT SUM(amount) as total FROM payments WHERE loan_id = ?', (loan_id,)).fetchone()
    
    if total_paid['total'] and float(total_paid['total']) >= float(loan['total_amount']):
        conn.execute('UPDATE loans SET status = "paid" WHERE id = ?', (loan_id,))
    
    conn.commit()
    conn.close()
    
    flash('Pagamento registrado com sucesso!')
    return redirect(url_for('loan_detail', loan_id=loan_id))

# API endpoints
@app.route('/api/profit_data')
@login_required
def api_profit_data():
    org_id = get_user_organization()
    conn = get_db_connection()
    
    # Buscar dados de empréstimos por mês
    monthly_data = conn.execute('''
        SELECT 
            strftime('%Y', l.loan_date) as year,
            strftime('%m', l.loan_date) as month,
            SUM(l.amount) as total_lent,
            COUNT(l.id) as loan_count
        FROM loans l
        WHERE l.organization_id = ?
        GROUP BY strftime('%Y-%m', l.loan_date)
        ORDER BY year DESC, month DESC
    ''', (org_id,)).fetchall()
    
    # Buscar dados de pagamentos por mês
    payment_data = conn.execute('''
        SELECT 
            strftime('%Y', p.payment_date) as year,
            strftime('%m', p.payment_date) as month,
            SUM(p.amount) as total_received
        FROM payments p
        WHERE p.organization_id = ?
        GROUP BY strftime('%Y-%m', p.payment_date)
    ''', (org_id,)).fetchall()
    
    conn.close()
    
    # Criar dicionário para facilitar a busca de pagamentos
    payments_dict = {}
    for payment in payment_data:
        key = f"{payment['year']}-{payment['month']}"
        payments_dict[key] = float(payment['total_received']) if payment['total_received'] else 0
    
    # Combinar dados e calcular lucros
    profit_data = []
    month_names = {
        '01': 'Janeiro', '02': 'Fevereiro', '03': 'Março', '04': 'Abril',
        '05': 'Maio', '06': 'Junho', '07': 'Julho', '08': 'Agosto',
        '09': 'Setembro', '10': 'Outubro', '11': 'Novembro', '12': 'Dezembro'
    }
    
    for loan_month in monthly_data:
        key = f"{loan_month['year']}-{loan_month['month']}"
        total_lent = float(loan_month['total_lent']) if loan_month['total_lent'] else 0
        total_received = payments_dict.get(key, 0)
        profit = total_received - total_lent
        margin = (profit / total_lent * 100) if total_lent > 0 else 0
        
        profit_data.append({
            'year': int(loan_month['year']),
            'month': loan_month['month'],
            'month_name': month_names.get(loan_month['month'], loan_month['month']),
            'total_lent': total_lent,
            'total_received': total_received,
            'profit': profit,
            'margin': margin,
            'loan_count': loan_month['loan_count']
        })
    
    return jsonify(profit_data)

@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    org_id = get_user_organization()
    conn = get_db_connection()
    
    # Dados para gráficos
    monthly_loans = conn.execute('''
        SELECT strftime('%Y-%m', loan_date) as month,
               SUM(amount) as total_amount,
               COUNT(*) as loan_count
        FROM loans
        WHERE loan_date >= date('now', '-12 months') AND organization_id = ?
        GROUP BY strftime('%Y-%m', loan_date)
        ORDER BY month
    ''', (org_id,)).fetchall()
    
    payment_stats = conn.execute('''
        SELECT strftime('%Y-%m', payment_date) as month,
               SUM(amount) as total_amount
        FROM payments
        WHERE payment_date >= date('now', '-12 months') AND organization_id = ?
        GROUP BY strftime('%Y-%m', payment_date)
        ORDER BY month
    ''', (org_id,)).fetchall()
    
    conn.close()
    
    return jsonify({
        'monthly_loans': [dict(row) for row in monthly_loans],
        'payment_stats': [dict(row) for row in payment_stats]
    })

if __name__ == '__main__':
    init_db()
    insert_sample_data()
    app.run(host='0.0.0.0', port=5000, debug=True)
