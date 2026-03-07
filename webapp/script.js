const tg = window.Telegram.WebApp;
tg.expand();

const userId = tg.initDataUnsafe?.user?.id;
if (!userId) {
    alert("Ошибка: не удалось получить данные пользователя");
}

let currentBalance = 0;
let currentGame = 'rocket'; // rocket / duel
let rocketActive = false;
let rocketInterval = null;
let currentDuelGameId = null;

// Элементы
const balanceSpan = document.getElementById('balance');
const rocketCard = document.getElementById('rocketCard');
const duelCard = document.getElementById('duelCard');
const rocketGame = document.getElementById('rocketGame');
const duelGame = document.getElementById('duelGame');
const multiplierSpan = document.getElementById('multiplier');
const eventMessage = document.getElementById('eventMessage');
const betInput = document.getElementById('betAmount');
const startRocketBtn = document.getElementById('startRocket');
const cashoutRocketBtn = document.getElementById('cashoutRocket');
const duelsList = document.getElementById('duelsList');
const duelBetInput = document.getElementById('duelBet');
const createDuelBtn = document.getElementById('createDuel');
const duelLobby = document.getElementById('duelLobby');
const duelActive = document.getElementById('duelActive');
const player1Span = document.getElementById('player1');
const player2Span = document.getElementById('player2');
const prob1Span = document.getElementById('prob1');
const prob2Span = document.getElementById('prob2');
const spinDuelBtn = document.getElementById('spinDuel');
const duelResultDiv = document.getElementById('duelResult');

// Загрузка баланса
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
updateBalance();

// Переключение игр по карточкам
rocketCard.addEventListener('click', () => {
    rocketCard.classList.add('active');
    duelCard.classList.remove('active');
    rocketGame.style.display = 'block';
    duelGame.style.display = 'none';
    currentGame = 'rocket';
});

duelCard.addEventListener('click', () => {
    duelCard.classList.add('active');
    rocketCard.classList.remove('active');
    duelGame.style.display = 'block';
    rocketGame.style.display = 'none';
    currentGame = 'duel';
    loadDuels();
});

// ================== РАКЕТА ==================
startRocketBtn.addEventListener('click', async () => {
    const bet = parseInt(betInput.value);
    if (isNaN(bet) || bet <= 0) return alert('Введите корректную ставку');
    if (bet > currentBalance) return alert('Недостаточно средств');

    const response = await fetch('/bet_rocket', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, bet: bet })
    });
    const data = await response.json();
    if (data.error) return alert(data.error);

    await updateBalance();
    rocketActive = true;
    startRocketBtn.disabled = true;
    cashoutRocketBtn.disabled = false;
    multiplierSpan.textContent = '1.00x';
    eventMessage.textContent = '';

    if (rocketInterval) clearInterval(rocketInterval);
    rocketInterval = setInterval(async () => {
        if (!rocketActive) return;
        const statusResp = await fetch('/rocket_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const status = await statusResp.json();
        if (status.error) {
            rocketActive = false;
            clearInterval(rocketInterval);
            startRocketBtn.disabled = false;
            cashoutRocketBtn.disabled = true;
            return;
        }
        if (status.crashed) {
            multiplierSpan.textContent = status.multiplier.toFixed(2) + 'x 💥';
            eventMessage.textContent = 'Ракета упала!';
            rocketActive = false;
            clearInterval(rocketInterval);
            startRocketBtn.disabled = false;
            cashoutRocketBtn.disabled = true;
            updateBalance();
        } else {
            multiplierSpan.textContent = status.multiplier.toFixed(2) + 'x';
            if (status.event) eventMessage.textContent = status.event.text;
        }
    }, 200);
});

cashoutRocketBtn.addEventListener('click', async () => {
    if (!rocketActive) return;
    const response = await fetch('/cashout_rocket', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    });
    const data = await response.json();
    if (data.error) return alert(data.error);
    if (data.win > 0) alert(`Вы выиграли ${data.win} монет!`);
    else alert('Ракета упала, вы ничего не выиграли.');
    rocketActive = false;
    clearInterval(rocketInterval);
    startRocketBtn.disabled = false;
    cashoutRocketBtn.disabled = true;
    updateBalance();
});

// ================== ДУЭЛЬ ==================
async function loadDuels() {
    const response = await fetch('/list_duels');
    const games = await response.json();
    duelsList.innerHTML = '';
    if (games.length === 0) {
        duelsList.innerHTML = '<div class="duel-item">Нет активных дуэлей</div>';
        return;
    }
    games.forEach(game => {
        const div = document.createElement('div');
        div.className = 'duel-item';
        div.innerHTML = `
            <span>Игрок ${game.player1}</span>
            <span>💰 ${game.bet1}</span>
            <button class="join-duel" data-id="${game.id}" data-bet="${game.bet1}">Присоединиться</button>
        `;
        duelsList.appendChild(div);
    });
    document.querySelectorAll('.join-duel').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const gameId = e.target.dataset.id;
            const bet1 = parseInt(e.target.dataset.bet);
            const myBet = prompt('Введите вашу ставку (минимум 1):', bet1);
            if (!myBet) return;
            const bet = parseInt(myBet);
            if (isNaN(bet) || bet <= 0) return alert('Некорректная ставка');
            const response = await fetch('/join_duel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, game_id: gameId, bet: bet })
            });
            const data = await response.json();
            if (data.error) return alert(data.error);
            currentDuelGameId = gameId;
            await loadDuelGame(gameId);
        });
    });
}

async function loadDuelGame(gameId) {
    const response = await fetch('/duel_status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game_id: gameId })
    });
    const game = await response.json();
    if (game.error) return;
    duelLobby.style.display = 'none';
    duelActive.style.display = 'block';
    player1Span.innerHTML = `👤 Игрок ${game.player1}<br>💰 ${game.bet1}`;
    player2Span.innerHTML = `👤 Игрок ${game.player2}<br>💰 ${game.bet2}`;
    const total = game.bet1 + game.bet2;
    const prob1 = ((game.bet1 / total) * 100).toFixed(1);
    const prob2 = ((game.bet2 / total) * 100).toFixed(1);
    prob1Span.textContent = prob1 + '%';
    prob2Span.textContent = prob2 + '%';
    spinDuelBtn.disabled = false;
    spinDuelBtn.onclick = async () => {
        spinDuelBtn.disabled = true;
        const spinResp = await fetch('/duel_spin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ game_id: gameId })
        });
        const result = await spinResp.json();
        if (result.error) return alert(result.error);
        duelResultDiv.innerHTML = `Победитель: Игрок ${result.winner}<br>Выигрыш: ${result.win_amount} монет`;
        await updateBalance();
        setTimeout(() => {
            duelLobby.style.display = 'block';
            duelActive.style.display = 'none';
            currentDuelGameId = null;
            loadDuels();
        }, 3000);
    };
}

createDuelBtn.addEventListener('click', async () => {
    const bet = parseInt(duelBetInput.value);
    if (isNaN(bet) || bet <= 0) return alert('Введите ставку');
    if (bet > currentBalance) return alert('Недостаточно средств');
    const response = await fetch('/create_duel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, bet: bet })
    });
    const data = await response.json();
    if (data.error) return alert(data.error);
    alert('Дуэль создана! Ожидайте соперника.');
    duelBetInput.value = '';
    loadDuels();
});

// Периодическое обновление списка дуэлей, если мы в лобби
setInterval(() => {
    if (currentGame === 'duel' && duelLobby.style.display !== 'none') {
        loadDuels();
    }
}, 5000);
