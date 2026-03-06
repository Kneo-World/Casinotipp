const tg = window.Telegram.WebApp;
tg.expand(); // Растягиваем на весь экран

// Получаем данные пользователя
const userId = tg.initDataUnsafe?.user?.id;
if (!userId) {
    alert("Ошибка: не удалось получить данные пользователя");
}

let currentBalance = 0;

// Элементы интерфейса
const balanceSpan = document.getElementById('balance');
const crashGameDiv = document.getElementById('crashGame');
const rouletteGameDiv = document.getElementById('rouletteGame');
const btnCrash = document.getElementById('btnCrash');
const btnRoulette = document.getElementById('btnRoulette');
const multiplierSpan = document.getElementById('multiplier');
const eventMessage = document.getElementById('eventMessage');
const betInput = document.getElementById('betAmount');
const startCrashBtn = document.getElementById('startCrash');
const cashoutBtn = document.getElementById('cashoutBtn');
const rouletteWheel = document.getElementById('rouletteWheel');
const rouletteNumberInput = document.getElementById('rouletteNumber');
const betNumberBtn = document.getElementById('betNumber');

// Состояние игры
let crashActive = false;
let crashInterval = null;

// Функция обновления баланса с сервера
async function updateBalance() {
    const response = await fetch('/get_balance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    });
    const data = await response.json();
    currentBalance = data.balance;
    balanceSpan.textContent = currentBalance;
}

// Вызов при загрузке
updateBalance();

// Переключение игр
btnCrash.addEventListener('click', () => {
    btnCrash.classList.add('active');
    btnRoulette.classList.remove('active');
    crashGameDiv.classList.add('active');
    rouletteGameDiv.classList.remove('active');
});

btnRoulette.addEventListener('click', () => {
    btnRoulette.classList.add('active');
    btnCrash.classList.remove('active');
    rouletteGameDiv.classList.add('active');
    crashGameDiv.classList.remove('active');
});

// ================== ИГРА "САМОЛЁТ" ==================
startCrashBtn.addEventListener('click', async () => {
    const bet = parseInt(betInput.value);
    if (isNaN(bet) || bet <= 0) {
        alert("Введите корректную ставку");
        return;
    }
    if (bet > currentBalance) {
        alert("Недостаточно средств");
        return;
    }

    const response = await fetch('/bet_crash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, bet: bet })
    });
    const data = await response.json();
    if (data.error) {
        alert(data.error);
        return;
    }

    // Обновляем баланс (ставка удержана)
    await updateBalance();

    // Запускаем игру
    crashActive = true;
    startCrashBtn.disabled = true;
    cashoutBtn.disabled = false;
    multiplierSpan.textContent = "1.00x";
    eventMessage.textContent = "";

    // Периодически запрашиваем статус
    if (crashInterval) clearInterval(crashInterval);
    crashInterval = setInterval(async () => {
        if (!crashActive) return;

        const statusResp = await fetch('/crash_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const status = await statusResp.json();

        if (status.error) {
            // Игра уже не активна (возможно, краш)
            crashActive = false;
            clearInterval(crashInterval);
            startCrashBtn.disabled = false;
            cashoutBtn.disabled = true;
            return;
        }

        if (status.crashed) {
            multiplierSpan.textContent = status.multiplier.toFixed(2) + "x 💥";
            eventMessage.textContent = "Самолёт упал!";
            crashActive = false;
            clearInterval(crashInterval);
            startCrashBtn.disabled = false;
            cashoutBtn.disabled = true;
            updateBalance();
        } else {
            multiplierSpan.textContent = status.multiplier.toFixed(2) + "x";
            if (status.event) {
                eventMessage.textContent = status.event.text;
                // Применим эффект события (сервер уже учёл, просто показываем)
            }
        }
    }, 200);
});

cashoutBtn.addEventListener('click', async () => {
    if (!crashActive) return;

    const response = await fetch('/cashout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    });
    const data = await response.json();
    if (data.error) {
        alert(data.error);
        return;
    }

    if (data.win > 0) {
        alert(`Вы выиграли ${data.win} монет!`);
    } else {
        alert("Самолёт упал, вы ничего не выиграли.");
    }

    crashActive = false;
    clearInterval(crashInterval);
    startCrashBtn.disabled = false;
    cashoutBtn.disabled = true;
    updateBalance();
});

// ================== РУЛЕТКА ==================
document.querySelectorAll('.bet-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
        const betType = e.target.dataset.type;
        const bet = parseInt(betInput.value);
        if (isNaN(bet) || bet <= 0) {
            alert("Введите ставку в поле выше");
            return;
        }
        if (bet > currentBalance) {
            alert("Недостаточно средств");
            return;
        }

        // Анимация вращения
        rouletteWheel.style.transform = 'rotate(720deg)';
        setTimeout(() => rouletteWheel.style.transform = 'rotate(0deg)', 2000);

        const response = await fetch('/roulette_bet', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                bet: bet,
                type: betType
            })
        });
        const data = await response.json();
        if (data.error) {
            alert(data.error);
            return;
        }

        // Показываем результат
        rouletteWheel.textContent = data.result_number;
        if (data.win > 0) {
            alert(`Выигрыш ${data.win} монет! Число: ${data.result_number}`);
        } else {
            alert(`Проигрыш. Число: ${data.result_number}`);
        }
        await updateBalance();
    });
});

betNumberBtn.addEventListener('click', async () => {
    const number = parseInt(rouletteNumberInput.value);
    if (isNaN(number) || number < 0 || number > 36) {
        alert("Введите число от 0 до 36");
        return;
    }
    const bet = parseInt(betInput.value);
    if (isNaN(bet) || bet <= 0) {
        alert("Введите ставку в поле выше");
        return;
    }
    if (bet > currentBalance) {
        alert("Недостаточно средств");
        return;
    }

    // Анимация
    rouletteWheel.style.transform = 'rotate(720deg)';
    setTimeout(() => rouletteWheel.style.transform = 'rotate(0deg)', 2000);

    const response = await fetch('/roulette_bet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: userId,
            bet: bet,
            type: 'number',
            number: number
        })
    });
    const data = await response.json();
    if (data.error) {
        alert(data.error);
        return;
    }

    rouletteWheel.textContent = data.result_number;
    if (data.win > 0) {
        alert(`Выигрыш ${data.win} монет! Число: ${data.result_number}`);
    } else {
        alert(`Проигрыш. Число: ${data.result_number}`);
    }
    await updateBalance();
});
