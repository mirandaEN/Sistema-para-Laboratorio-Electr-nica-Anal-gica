## Sistema de Gestión de Laboratorio


Este proyecto implementa un sistema web para el control de acceso y registro en un laboratorio de Electrónica / Analógica del Instituto Tecnológico de Saltillo. Permite gestionar usuarios (Jefe de Laboratorio y Auxiliares) y registrar alumnos con sus datos académicos.
## Tecnologías utilizadas
- Python 3
- Flask
- Oracle Database (XE)
- HTML / CSS
  
**Estructura del proyecto**

ISW/
│
├── app.py                 
├── templates/             
│   ├── inicioAdmin.html
│   └── inicioAlumno.html
├── static/
│   ├── css/
│   │   └── stile.css
│   └── sources/
│       └── itislogo.png

**Requisitos previos**
- Tener instalado Python 3.
- Tener instalado Oracle XE y configurado con cx_Oracle.
- Tener Flask instalado:
```bash
pip install flask cx_Oracle
```
## Ejecución
1. Ejecuta la aplicación desde la terminal:
```bash
python3 app.py
```

2. Abre tu navegador y entra a: http://127.0.0.1:5000/

3. Para acceder al login de administradores (Jefe/Auxiliar) usar inicioAdmin.html y para registro de alumnos usar inicioAlumno.html.


## Funcionalidades
- **Login de administradores**
- Validación de usuario y contraseña.
- Distinción entre Jefe de Laboratorio y Auxiliar.
- Mensajes de error según los casos:
- Ingresa tu usuario / contraseña
- Verifica tu usuario y contraseña
- El usuario y contraseña que ingresaste no existen
- **Registro de alumnos**
- Ingreso de nombre, número de control, correo institucional, especialidad y semestre.
- Validación de datos y registro en la base de datos.
- Mensaje de éxito o error al registrar un alumno.

**Notas importantes**
- El sistema **no** permite números en los nombres de usuario.
- Los campos de usuario y contraseña tienen límite de 50 caracteres (controlado desde el frontend).
- Todos los correos institucionales deben empezar con la letra "l" seguida del número de control.


**Ejemplo de uso**

Login Jefe de Laboratorio:

Usuario: Alberto Gomez

Contraseña: AG123

Registro de Alumno:

Nombre: Miranda Estrada Neyra

Número de control: 22050751

Correo institucional: l22050751@saltillo.tecnm.mx

Especialidad: Sistemas

Semestre: 7

Al enviar el formulario, el alumno se registrará en la base de datos y mostrará un mensaje de éxito.
