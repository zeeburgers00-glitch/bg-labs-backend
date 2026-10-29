<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// Database config
$DB_HOST = getenv('DB_HOST') ?: 'localhost';
$DB_NAME = getenv('DB_NAME') ?: '';
$DB_USER = getenv('DB_USER') ?: '';
$DB_PASS = getenv('DB_PASS') ?: '';
$SECRET = getenv('APP_SECRET') ?: 'change-me';

// Connect to MySQL
try {
    $pdo = new PDO("mysql:host=$DB_HOST;dbname=$DB_NAME;charset=utf8mb4", $DB_USER, $DB_PASS, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
    ]);
} catch (PDOException $e) {
    echo json_encode(['error' => 'Database connection failed', 'detail' => $e->getMessage()]);
    exit;
}

// Create tables
$pdo->exec("CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) DEFAULT '',
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active INT DEFAULT 1,
    credits INT DEFAULT 999999,
    total_used INT DEFAULT 0,
    referral_code VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)");

$pdo->exec("CREATE TABLE IF NOT EXISTS audio_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    text TEXT,
    voice VARCHAR(100),
    language VARCHAR(50),
    model VARCHAR(100),
    filename VARCHAR(255),
    url VARCHAR(500),
    chars INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)");

$pdo->exec("CREATE TABLE IF NOT EXISTS image_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    prompt TEXT,
    style VARCHAR(100),
    filename VARCHAR(255),
    url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)");

// Helpers
function hash_pass($p) { return hash('sha256', $p); }
function create_token($user_id, $secret) {
    $payload = json_encode(['user_id' => $user_id, 'exp' => time() + 86400 * 30]);
    return base64_encode($payload) . '.' . hash_hmac('sha256', $payload, $secret);
}
function decode_token($token, $secret) {
    $parts = explode('.', $token);
    if (count($parts) !== 2) return null;
    $payload = json_decode(base64_decode($parts[0]), true);
    $sig = hash_hmac('sha256', $parts[0], $secret);
    if ($payload['exp'] < time() || $sig !== $parts[1]) return null;
    return $payload['user_id'];
}

function get_user($pdo, $token, $secret) {
    if (!$token) return null;
    $user_id = decode_token(str_replace('Bearer ', '', $token), $secret);
    if (!$user_id) return null;
    $stmt = $pdo->prepare("SELECT * FROM users WHERE id = ?");
    $stmt->execute([$user_id]);
    return $stmt->fetch();
}

function json_response($data, $code = 200) {
    http_response_code($code);
    echo json_encode($data);
    exit;
}

// Route
$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$path = str_replace('/api', '', $path);

$auth_header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';

// ===== AUTH =====
if ($path === '/auth/register' && $method === 'POST') {
    $email = $_POST['email'] ?? '';
    $username = $_POST['username'] ?? '';
    $full_name = $_POST['full_name'] ?? '';
    $password = $_POST['password'] ?? '';
    
    if (!$email || !$username || !$password) json_response(['error' => 'Missing fields'], 400);
    
    $stmt = $pdo->prepare("SELECT 1 FROM users WHERE email = ? OR username = ?");
    $stmt->execute([$email, $username]);
    if ($stmt->fetch()) json_response(['error' => 'Email or username already exists'], 400);
    
    $hash = hash_pass($password);
    $code = substr(md5(uniqid()), 0, 8);
    
    $stmt = $pdo->prepare("INSERT INTO users (email, username, full_name, password_hash, referral_code) VALUES (?, ?, ?, ?, ?)");
    $stmt->execute([$email, $username, $full_name, $hash, $code]);
    $user_id = $pdo->lastInsertId();
    
    $token = create_token($user_id, $SECRET);
    $stmt = $pdo->prepare("SELECT * FROM users WHERE id = ?");
    $stmt->execute([$user_id]);
    $user = $stmt->fetch();
    
    json_response(['access_token' => $token, 'token_type' => 'bearer', 'user' => [
        'id' => $user['id'], 'email' => $user['email'], 'username' => $user['username'],
        'full_name' => $user['full_name'], 'role' => $user['role'], 'credits' => $user['credits']
    ]]);
}

if ($path === '/auth/login' && $method === 'POST') {
    $username = $_POST['username'] ?? '';
    $password = $_POST['password'] ?? '';
    
    $stmt = $pdo->prepare("SELECT * FROM users WHERE username = ? OR email = ?");
    $stmt->execute([$username, $username]);
    $user = $stmt->fetch();
    
    if (!$user || !hash_equals($user['password_hash'], hash_pass($password))) {
        json_response(['error' => 'Invalid credentials'], 401);
    }
    
    $token = create_token($user['id'], $SECRET);
    json_response(['access_token' => $token, 'token_type' => 'bearer', 'user' => [
        'id' => $user['id'], 'email' => $user['email'], 'username' => $user['username'],
        'full_name' => $user['full_name'], 'role' => $user['role'], 'credits' => $user['credits']
    ]]);
}

if ($path === '/auth/me') {
    $user = get_user($pdo, $auth_header, $SECRET);
    if (!$user) json_response(['error' => 'Unauthorized'], 401);
    
    if ($method === 'GET') {
        json_response([
            'id' => $user['id'], 'email' => $user['email'], 'username' => $user['username'],
            'full_name' => $user['full_name'], 'role' => $user['role'], 'is_active' => (bool)$user['is_active'],
            'credits' => $user['credits'], 'total_credits_used' => $user['total_used'],
            'referral_code' => $user['referral_code'], 'created_at' => $user['created_at']
        ]);
    }
    if ($method === 'PUT') {
        $data = json_decode(file_get_contents('php://input'), true);
        if (isset($data['full_name'])) {
            $stmt = $pdo->prepare("UPDATE users SET full_name = ? WHERE id = ?");
            $stmt->execute([$data['full_name'], $user['id']]);
        }
        json_response(['ok' => true]);
    }
}

// ===== VOICES =====
if ($path === '/voices') {
    json_response(['total' => 175, 'engine' => 'Edge TTS (FREE)']);
}

// ===== ADMIN =====
if ($path === '/admin/stats' && $method === 'GET') {
    $user = get_user($pdo, $auth_header, $SECRET);
    if (!$user || $user['role'] !== 'admin') json_response(['error' => 'Admin only'], 403);
    
    $users = $pdo->query("SELECT COUNT(*) FROM users")->fetchColumn();
    $audio = $pdo->query("SELECT COUNT(*) FROM audio_history")->fetchColumn();
    $images = $pdo->query("SELECT COUNT(*) FROM image_history")->fetchColumn();
    $chars = $pdo->query("SELECT COALESCE(SUM(total_used), 0) FROM users")->fetchColumn();
    
    json_response(['total_users' => $users, 'total_audio' => $audio, 'total_images' => $images, 'total_credits_used' => $chars]);
}

if ($path === '/admin/users' && $method === 'GET') {
    $user = get_user($pdo, $auth_header, $SECRET);
    if (!$user || $user['role'] !== 'admin') json_response(['error' => 'Admin only'], 403);
    
    $stmt = $pdo->query("SELECT id, email, username, full_name, role, is_active, credits, total_used, referral_code, created_at FROM users ORDER BY id DESC");
    $users = $stmt->fetchAll();
    json_response(['users' => $users]);
}

// ===== ROOT =====
if ($path === '/' || $path === '') {
    json_response(['name' => 'BG LABS API', 'version' => '5.0.0', 'status' => 'running', 'engine' => 'PHP + MySQL']);
}

if ($path === '/health') {
    json_response(['status' => 'healthy']);
}

json_response(['error' => 'Not found'], 404);
?>