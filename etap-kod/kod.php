<?php
/* ETAP Kilit - harici karekod sayfası.  Gereksinim: PHP 7.3+ (HTTPS önerilir). */
declare(strict_types=1);
$C = require __DIR__ . '/config.php';
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');
header('Referrer-Policy: no-referrer');
header('X-Robots-Tag: noindex, nofollow');

const CSS = 'body{font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0B1020,#16213A);color:#E8ECF8}.c{width:min(400px,92vw);background:#18223D;border:1px solid #2A3A66;border-radius:20px;padding:28px;text-align:center}h1{font-size:20px;margin:0 0 4px}p{color:#8FA0C4;margin:6px 0 16px}label{display:block;text-align:left;color:#8FA0C4}input,button{font-size:18px;padding:14px;width:100%;margin:6px 0;box-sizing:border-box;border-radius:12px;border:1px solid #2A3A66}input{background:#0B1020;color:#fff}input[type=checkbox]{width:auto;margin-right:8px}button{background:#4F8CFF;color:#fff;border:0;font-weight:600}.pin{font-size:54px;letter-spacing:10px;font-weight:700;margin:18px 0;color:#F5B301}.e{color:#F87171}';

function h(string $s): string { return htmlspecialchars($s, ENT_QUOTES, 'UTF-8'); }
function hm(string $secret, string $msg): string { return hash_hmac('sha256', $msg, $secret); }
function code6(string $secret, string $b, string $n, string $t): string {
    $d = hm($secret, "code|$b|$n|$t");
    return str_pad((string)((hexdec(substr($d, 0, 8)) & 0x7fffffff) % 1000000), 6, '0', STR_PAD_LEFT);
}
function b64u(string $s): string { return rtrim(strtr(base64_encode($s), '+/', '-_'), '='); }
function b64ud(string $s): string { return (string)base64_decode(strtr($s, '-_', '+/')); }
function dev_sig(array $C, string $payload): string {
    return substr(hash_hmac('sha256', $payload, $C['secret'] . '|dev|' . $C['ver']), 0, 32);
}
function page(array $C, string $body): void {
    echo '<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
       . '<title>' . h($C['school']) . '</title><style>' . CSS . '</style><div class="c"><h1>' . h($C['school']) . '</h1>' . $body . '</div></html>';
}
function verify_cookie(array $C): ?string {
    $v = $_COOKIE['etap_t'] ?? '';
    if (!is_string($v) || strpos($v, '.') === false) return null;
    [$payload, $sig] = explode('.', $v, 2);
    if (!hash_equals(dev_sig($C, $payload), $sig)) return null;
    $d = json_decode(b64ud($payload), true);
    if (!is_array($d) || (int)($d['v'] ?? 0) !== (int)$C['ver'] || (int)($d['e'] ?? 0) < time()) return null;
    $n = trim((string)($d['n'] ?? ''));
    return $n !== '' ? $n : 'Öğretmen';
}
/* Kaba kuvvet koruması: IP başına 10 dakikada en fazla 8 hatalı kod */
function rl_file(): string { return sys_get_temp_dir() . '/etap_rl_' . md5((string)($_SERVER['REMOTE_ADDR'] ?? 'x')); }
function rl_read(): array {
    $f = rl_file();
    if (!is_file($f)) return [0, time()];
    $p = array_map('intval', explode('|', (string)@file_get_contents($f)) + [0, 0]);
    if (time() - $p[1] > 600) { @unlink($f); return [0, time()]; }
    return [$p[0], $p[1]];
}
function rl_blocked(): bool { return rl_read()[0] >= 8; }
function rl_fail(): void { $r = rl_read(); @file_put_contents(rl_file(), ($r[0] + 1) . '|' . $r[1], LOCK_EX); }
function rl_ok(): void { @unlink(rl_file()); }

$src = ($_SERVER['REQUEST_METHOD'] === 'POST') ? $_POST : $_GET;
$b = (string)($src['b'] ?? ''); $n = (string)($src['n'] ?? ''); $t = (string)($src['t'] ?? ''); $s = (string)($src['s'] ?? '');

$valid = $b !== '' && strlen($b) <= 64 && preg_match('/^[A-Za-z0-9_-]{6,40}$/', $n)
      && ctype_digit($t) && strlen($t) <= 12 && preg_match('/^[0-9a-f]{32}$/', $s);
if (!$valid || !hash_equals(substr(hm($C['secret'], "$b|$n|$t"), 0, 32), $s)) {
    page($C, '<p class="e">Geçersiz karekod.</p><p>Lütfen tahtadaki karekodu okutun.</p>');
    exit;
}
$age = time() - (int)$t;
if ($age > $C['ttl'] + $C['skew'] || $age < -300) {
    page($C, '<p class="e">Karekodun süresi doldu.</p><p>Tahtadaki yenilenmiş karekodu okutun.</p>');
    exit;
}
$remain = max(0, $C['ttl'] - max(0, $age));

$name = verify_cookie($C);
$err = '';
if ($name === null && $_SERVER['REQUEST_METHOD'] === 'POST') {
    if (rl_blocked()) {
        $err = 'Çok fazla hatalı deneme. 10 dakika sonra tekrar deneyin.';
    } else {
        $code = trim((string)($_POST['code'] ?? ''));
        if (hash_equals($C['code_hash'], hash('sha256', $C['code_salt'] . $code))) {
            rl_ok();
            $nm = trim((string)($_POST['name'] ?? ''));
            $nm = function_exists('mb_substr') ? mb_substr($nm, 0, 40) : substr($nm, 0, 40);
            $name = $nm !== '' ? $nm : 'Öğretmen';
            if (!empty($_POST['remember'])) {
                $exp = time() + (int)$C['remember_days'] * 86400;
                $payload = b64u((string)json_encode(['n' => $name, 'e' => $exp, 'v' => (int)$C['ver']], JSON_UNESCAPED_UNICODE));
                setcookie('etap_t', $payload . '.' . dev_sig($C, $payload),
                    ['expires' => $exp, 'path' => '/', 'secure' => !empty($_SERVER['HTTPS']), 'httponly' => true, 'samesite' => 'Lax']);
            }
        } else {
            rl_fail();
            $err = 'Öğretmen kodu hatalı.';
        }
    }
}

if ($name !== null) {
    $code = code6($C['secret'], $b, $n, $t);
    page($C, '<p>Merhaba <b>' . h($name) . '</b>, tahtaya şu PIN\'i girin:</p><div class="pin">' . $code . '</div>'
      . '<p id="m">Bu kod <b id="cd">' . (int)$remain . '</b> sn geçerli ve tek kullanımlıktır.</p>'
      . '<script>var r=' . (int)$remain . ',e=document.getElementById("cd");var iv=setInterval(function(){r--;'
      . 'if(r<=0){clearInterval(iv);document.querySelector(".pin").textContent="- - -";'
      . 'document.getElementById("m").textContent="Süre doldu. Karekodu yeniden okutun.";return;}e.textContent=r;},1000);</script>');
    exit;
}

$hid = '';
foreach (['b' => $b, 'n' => $n, 't' => $t, 's' => $s] as $k => $v) {
    $hid .= '<input type="hidden" name="' . $k . '" value="' . h($v) . '">';
}
page($C, '<p>Tahta: <b>' . h($b) . '</b></p>' . ($err !== '' ? '<p class="e">' . h($err) . '</p>' : '')
  . '<form method="post">' . $hid
  . '<input name="name" placeholder="Adınız Soyadınız (isteğe bağlı)" autocomplete="name">'
  . '<input name="code" type="password" placeholder="Öğretmen kodu" autocomplete="off">'
  . '<label><input type="checkbox" name="remember" value="1" checked>Bu telefonu hatırla</label>'
  . '<button>PIN Üret</button></form>');
