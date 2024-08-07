import sqlite3

connection = sqlite3.connect("axi.db")
cursor = connection.cursor()

def add_game(name):
    command = ""
    command += f"CREATE TABLE IF NOT EXISTS {name}(\n"
    command += f"user_id INT PRIMARY KEY,\n"
    command += f"profile BLOB,\n"
    command += "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);"
    cursor.execute(command)
    connection.commit()

def add_table(db_name, columns):
    command = ""
    command += f"CREATE TABLE IF NOT EXISTS {db_name}(\n"
    command += f"primary_id INT PRIMARY KEY AUTO_INCREMENT,\n"
    for c in columns:
        command += f"{c[0]} {c[1]},\n"
    command += "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);"
    cursor.execute(command)
    connection.commit()

def add_entry(db_name, entry, replace=True):
    if replace:
        sql_command = "INSERT OR REPLACE INTO " + db_name + "("
    else:
        sql_command = "INSERT OR IGNORE INTO" + db_name + "("
    column_names = get_column_names(db_name)
    for i in range(len(column_names)):
        if i > 0:
            sql_command += ", "
        sql_command += column_names[i]
    sql_command += ") VALUES("
    for i in range(len(entry)):
        if i > 0:
            sql_command += ", "
        sql_command += "?"
    sql_command += ");"
    cursor.execute(sql_command, entry)
    connection.commit()
    return cursor.lastrowid

def load_entry_multiwhere(db_name, flag_pairs):
    sql_command = f"SELECT * FROM {db_name} WHERE "
    for i in range(len(flag_pairs)):
        fp = flag_pairs[i]
        if i > 0:
            sql_command += " AND "
        if isinstance(fp[1], str):
            sql_command += f"{fp[0]}='{fp[1]}'"
        else:
            sql_command += f"{fp[0]}={fp[1]}"
    print(sql_command)
    cursor.execute(sql_command)
    connection.commit()
    return cursor.fetchall(), cursor.lastrowid

def load_entry_where(db_name, flag_name, flag_value):
    if isinstance(flag_value, str):
        sql_command = f"SELECT * FROM {db_name} WHERE {flag_name}='{flag_value}'"
    else:
        sql_command = f"SELECT * FROM {db_name} WHERE {flag_name}={flag_value}"
    cursor.execute(sql_command)
    connection.commit()
    return cursor.fetchone()

def load_entry(db_name, rowid):
    sql_command = "SELECT * FROM " + db_name + " WHERE rowid=" + str(rowid)
    cursor.execute(sql_command)
    connection.commit()
    return cursor.fetchone()

def load_all_entries(db_name):
    sql_command = "SELECT * FROM " + db_name
    cursor.execute(sql_command)
    connection.commit()
    return cursor.fetchall()

def run_command(sql_command):
    cursor.execute(sql_command)
    connection.commit()
    return cursor.fetchall()[-5:], cursor.lastrowid

def get_column_names(db_name):
    sql_command = "SELECT * FROM pragma_table_info('" + db_name + "') AS tblInfo;"
    cursor.execute(sql_command)
    connection.commit()
    fa = cursor.fetchall()
    return [x[1] for x in fa][:-1]
