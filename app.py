from flask import Flask, render_template, request, redirect, url_for, flash
import cx_Oracle
import re

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Inicializar Oracle Client
cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# Datos de conexión a Oracle
db_user = 'JEFE_LAB'
db_password = 'jefe123'
dsn = 'localhost:1521/XEPDB1'

#FUNCIONES

def validar_usuario(usuario, contrasena):
    """Valida login y devuelve tipo si usuario y contraseña son correctos"""
    try:
        connection = cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
        cursor = connection.cursor()
        cursor.execute("""
            SELECT tipo 
            FROM usuarios 
            WHERE usuario = :usr AND contrasena = :pwd
        """, usr=usuario, pwd=contrasena)
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        if result:
            return int(result[0])
        else:
            return None
    except cx_Oracle.DatabaseError as e:
        print("Error al conectar a Oracle:", e)
        return None

def usuario_existe(usuario):
    """Verifica si un usuario existe (sin validar contraseña)"""
    try:
        connection = cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM usuarios WHERE usuario = :usr", usr=usuario)
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result is not None
    except cx_Oracle.DatabaseError as e:
        print("Error al consultar usuario:", e)
        return False

def registrar_alumno(nombre, numero_control, correo):
    """Inserta un alumno en la tabla alumnos"""
    try:
        connection = cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO alumnos (nombre, numerocontrol, correo)
            VALUES (:nombre, :numero_control, :correo)
        """, nombre=nombre, numero_control=numero_control, correo=correo)
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except cx_Oracle.DatabaseError as e:
        print("Error al insertar alumno:", e)
        return False

# RUTAS JEFE/AUXILIAR

@app.route("/", methods=["GET", "POST"])
def login():
    """Login jefe/auxiliar"""
    mensaje = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()

        # Validación: usuario solo letras
        if usuario and not re.match(r"^[A-Za-zÁÉÍÓÚáéíóúÑñ ]+$", usuario):
            mensaje = "El usuario solo puede contener letras"
            return render_template("inicioAdmin.html", mensaje=mensaje)

        # Casos de prueba
        if not usuario and not contrasena:
            mensaje = "Ingresa tu usuario y contraseña"
        elif usuario and not contrasena:
            mensaje = "Ingresa tu contraseña"
        elif contrasena and not usuario:
            mensaje = "Ingresa tu usuario"
        else:
            tipo = validar_usuario(usuario, contrasena)
            if tipo is None:
                if usuario_existe(usuario):
                    mensaje = "Verifica tu usuario y contraseña"
                else:
                    mensaje = "El usuario y contraseña que ingresaste no existen"
            else:
                if tipo == 0:
                    return redirect(url_for("pagina_jefe"))
                elif tipo == 1:
                    return redirect(url_for("pagina_auxiliar"))

    return render_template("inicioAdmin.html", mensaje=mensaje)

@app.route("/jefe")
def pagina_jefe():
    return "<h1>Bienvenido Jefe de Laboratorio</h1>"

@app.route("/auxiliar")
def pagina_auxiliar():
    return "<h1>Bienvenido Auxiliar</h1>"

@app.route("/registro_alumno", methods=["GET", "POST"])
def registro_alumno():
    """Registro de alumnos"""
    mensaje = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        numero_control = request.form.get("numero_control", "").strip()
        correo = request.form.get("correo", "").strip()

        # Validaciones simples
        if not nombre or not numero_control or not correo:
            mensaje = "Completa todos los campos"
        elif len(numero_control) != 9 or not numero_control.isdigit():
            mensaje = "Número de control debe tener 9 dígitos"
        else:
            exito = registrar_alumno(nombre, numero_control, correo)
            if exito:
                mensaje = "Alumno registrado correctamente"
            else:
                mensaje = "Error al registrar alumno. Verifica los datos o si ya existe."

    return render_template("inicioAlumno.html", mensaje=mensaje)

# EJECUCIÓN

if __name__ == "__main__":
    app.run(debug=True)
