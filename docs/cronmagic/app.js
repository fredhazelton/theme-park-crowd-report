/**
 * CronMagic - Human-readable cron expressions
 * Built for the 24-hour startup challenge
 */

// DOM Elements
const englishInput = document.getElementById('english-input');
const cronInput = document.getElementById('cron-input');
const resultValue = document.getElementById('result-value');
const copyBtn = document.getElementById('copy-btn');
const runsList = document.getElementById('runs-list');
const modeButtons = document.querySelectorAll('.mode-btn');
const englishMode = document.getElementById('english-mode');
const cronMode = document.getElementById('cron-mode');
const quickPicks = document.querySelectorAll('.quick-pick');
const examples = document.querySelectorAll('.example');

let currentMode = 'english';
let currentResult = '';

// Day names
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 
                'July', 'August', 'September', 'October', 'November', 'December'];

// ============================================
// Natural Language to Cron Parser
// ============================================

function englishToCron(text) {
    const input = text.toLowerCase().trim();
    
    if (!input) return null;
    
    // Every minute
    if (/every\s*minute|each\s*minute|per\s*minute/.test(input)) {
        return '* * * * *';
    }
    
    // Every X minutes
    const everyMinutes = input.match(/every\s*(\d+)\s*min(ute)?s?/);
    if (everyMinutes) {
        const mins = parseInt(everyMinutes[1]);
        if (mins > 0 && mins < 60) {
            return `*/${mins} * * * *`;
        }
    }
    
    // Every hour / hourly
    if (/every\s*hour|hourly|each\s*hour/.test(input)) {
        return '0 * * * *';
    }
    
    // Every X hours
    const everyHours = input.match(/every\s*(\d+)\s*hours?/);
    if (everyHours) {
        const hrs = parseInt(everyHours[1]);
        if (hrs > 0 && hrs <= 23) {
            return `0 */${hrs} * * *`;
        }
    }
    
    // Daily at midnight
    if (/daily\s*(at\s*)?(midnight|12\s*am|0?0:00)/.test(input) || 
        /every\s*day\s*(at\s*)?(midnight|12\s*am|0?0:00)/.test(input) ||
        input === 'daily' || input === 'every day') {
        return '0 0 * * *';
    }
    
    // Daily at noon
    if (/daily\s*(at\s*)?(noon|12\s*pm|12:00)/.test(input) ||
        /every\s*day\s*(at\s*)?(noon|12\s*pm)/.test(input)) {
        return '0 12 * * *';
    }
    
    // Daily at specific time
    const dailyAt = input.match(/(?:daily|every\s*day)\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
    if (dailyAt) {
        let hour = parseInt(dailyAt[1]);
        const minute = dailyAt[2] ? parseInt(dailyAt[2]) : 0;
        const ampm = dailyAt[3]?.toLowerCase();
        
        if (ampm === 'pm' && hour < 12) hour += 12;
        if (ampm === 'am' && hour === 12) hour = 0;
        
        return `${minute} ${hour} * * *`;
    }
    
    // Weekly / every week
    if (/weekly|every\s*week/.test(input) && !/monday|tuesday|wednesday|thursday|friday|saturday|sunday/.test(input)) {
        return '0 0 * * 0';
    }
    
    // Specific day at time
    const dayPattern = /(?:every\s*)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i;
    const dayMatch = input.match(dayPattern);
    if (dayMatch) {
        const dayName = dayMatch[1].toLowerCase();
        let hour = parseInt(dayMatch[2]);
        const minute = dayMatch[3] ? parseInt(dayMatch[3]) : 0;
        const ampm = dayMatch[4]?.toLowerCase();
        
        if (ampm === 'pm' && hour < 12) hour += 12;
        if (ampm === 'am' && hour === 12) hour = 0;
        
        const dayNum = DAYS.findIndex(d => d.toLowerCase() === dayName);
        return `${minute} ${hour} * * ${dayNum}`;
    }
    
    // Just a day name
    const justDay = input.match(/(?:every\s*)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?$/i);
    if (justDay) {
        const dayName = justDay[1].toLowerCase();
        const dayNum = DAYS.findIndex(d => d.toLowerCase() === dayName);
        return `0 0 * * ${dayNum}`;
    }
    
    // Weekdays
    if (/weekdays?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i.test(input)) {
        const weekdayMatch = input.match(/weekdays?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
        let hour = parseInt(weekdayMatch[1]);
        const minute = weekdayMatch[2] ? parseInt(weekdayMatch[2]) : 0;
        const ampm = weekdayMatch[3]?.toLowerCase();
        
        if (ampm === 'pm' && hour < 12) hour += 12;
        if (ampm === 'am' && hour === 12) hour = 0;
        
        return `${minute} ${hour} * * 1-5`;
    }
    
    if (/weekdays?$|every\s*weekday/.test(input)) {
        return '0 9 * * 1-5';
    }
    
    // Weekends
    if (/weekends?/.test(input)) {
        const weekendMatch = input.match(/weekends?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
        if (weekendMatch && weekendMatch[1]) {
            let hour = parseInt(weekendMatch[1]);
            const minute = weekendMatch[2] ? parseInt(weekendMatch[2]) : 0;
            const ampm = weekendMatch[3]?.toLowerCase();
            
            if (ampm === 'pm' && hour < 12) hour += 12;
            if (ampm === 'am' && hour === 12) hour = 0;
            
            return `${minute} ${hour} * * 0,6`;
        }
        return '0 0 * * 0,6';
    }
    
    // Monthly / first of month
    if (/monthly|every\s*month|first\s*of\s*(?:every\s*)?month/.test(input)) {
        const monthMatch = input.match(/(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
        if (monthMatch && monthMatch[1]) {
            let hour = parseInt(monthMatch[1]);
            const minute = monthMatch[2] ? parseInt(monthMatch[2]) : 0;
            const ampm = monthMatch[3]?.toLowerCase();
            
            if (ampm === 'pm' && hour < 12) hour += 12;
            if (ampm === 'am' && hour === 12) hour = 0;
            
            return `${minute} ${hour} 1 * *`;
        }
        return '0 0 1 * *';
    }
    
    // Yearly / annually
    if (/yearly|annually|every\s*year/.test(input)) {
        return '0 0 1 1 *';
    }
    
    // At specific time only (assume daily)
    const timeOnly = input.match(/^(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/i);
    if (timeOnly) {
        let hour = parseInt(timeOnly[1]);
        const minute = timeOnly[2] ? parseInt(timeOnly[2]) : 0;
        const ampm = timeOnly[3]?.toLowerCase();
        
        if (ampm === 'pm' && hour < 12) hour += 12;
        if (ampm === 'am' && hour === 12) hour = 0;
        
        return `${minute} ${hour} * * *`;
    }
    
    return null;
}

// ============================================
// Cron to English Parser
// ============================================

function cronToEnglish(cron) {
    const parts = cron.trim().split(/\s+/);
    
    if (parts.length !== 5) {
        return 'Invalid cron expression (need 5 fields)';
    }
    
    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
    
    // Validate basic format
    const validField = /^(\*|(\d+(-\d+)?)(,\d+(-\d+)?)*|\*\/\d+|\d+\/\d+)$/;
    for (const part of parts) {
        if (!validField.test(part)) {
            return 'Invalid cron expression';
        }
    }
    
    // Every minute
    if (cron === '* * * * *') {
        return 'Every minute';
    }
    
    // Every X minutes
    if (minute.startsWith('*/') && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
        const mins = minute.slice(2);
        return `Every ${mins} minute${mins === '1' ? '' : 's'}`;
    }
    
    // Every hour
    if (minute === '0' && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
        return 'Every hour, on the hour';
    }
    
    // Every X hours
    if (minute === '0' && hour.startsWith('*/') && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
        const hrs = hour.slice(2);
        return `Every ${hrs} hour${hrs === '1' ? '' : 's'}`;
    }
    
    // Build description
    let desc = '';
    
    // Time description
    const timeDesc = describeTime(minute, hour);
    
    // Day description
    let dayDesc = '';
    
    if (dayOfMonth !== '*' && dayOfWeek === '*') {
        // Specific day of month
        if (dayOfMonth === '1') {
            dayDesc = 'on the 1st of every month';
        } else {
            dayDesc = `on day ${dayOfMonth} of every month`;
        }
    } else if (dayOfWeek !== '*' && dayOfMonth === '*') {
        // Specific day of week
        dayDesc = describeDayOfWeek(dayOfWeek);
    } else if (dayOfMonth === '*' && dayOfWeek === '*') {
        if (month === '*') {
            dayDesc = 'every day';
        }
    }
    
    // Month description
    let monthDesc = '';
    if (month !== '*') {
        const monthNum = parseInt(month);
        if (monthNum >= 1 && monthNum <= 12) {
            monthDesc = `in ${MONTHS[monthNum - 1]}`;
        }
    }
    
    // Combine
    desc = timeDesc;
    if (dayDesc) desc += ', ' + dayDesc;
    if (monthDesc) desc += ' ' + monthDesc;
    
    return desc.charAt(0).toUpperCase() + desc.slice(1);
}

function describeTime(minute, hour) {
    if (minute === '*' && hour === '*') {
        return 'every minute';
    }
    
    if (minute.startsWith('*/')) {
        return `every ${minute.slice(2)} minutes`;
    }
    
    if (hour === '*') {
        return `at minute ${minute} of every hour`;
    }
    
    const min = parseInt(minute) || 0;
    let hr = parseInt(hour);
    
    if (isNaN(hr)) {
        if (hour.startsWith('*/')) {
            return `every ${hour.slice(2)} hours at minute ${min}`;
        }
        return `at minute ${min}`;
    }
    
    const ampm = hr >= 12 ? 'PM' : 'AM';
    const displayHour = hr === 0 ? 12 : (hr > 12 ? hr - 12 : hr);
    const displayMin = min.toString().padStart(2, '0');
    
    return `at ${displayHour}:${displayMin} ${ampm}`;
}

function describeDayOfWeek(dow) {
    if (dow === '*') return '';
    if (dow === '0' || dow === '7') return 'on Sundays';
    if (dow === '1-5') return 'on weekdays (Mon-Fri)';
    if (dow === '0,6' || dow === '6,0') return 'on weekends';
    if (dow === '1-7' || dow === '0-6') return 'every day';
    
    // Range
    if (dow.includes('-')) {
        const [start, end] = dow.split('-').map(Number);
        return `${DAYS_SHORT[start]} through ${DAYS_SHORT[end]}`;
    }
    
    // List
    if (dow.includes(',')) {
        const days = dow.split(',').map(d => DAYS_SHORT[parseInt(d)]);
        return `on ${days.join(' and ')}`;
    }
    
    // Single day
    const dayNum = parseInt(dow);
    if (dayNum >= 0 && dayNum <= 7) {
        return `on ${DAYS[dayNum === 7 ? 0 : dayNum]}s`;
    }
    
    return '';
}

// ============================================
// Next Run Times Calculator
// ============================================

function getNextRuns(cron, count = 5) {
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return [];
    
    const [minField, hourField, domField, monthField, dowField] = parts;
    
    const runs = [];
    const now = new Date();
    let current = new Date(now);
    current.setSeconds(0);
    current.setMilliseconds(0);
    
    // Safety limit
    const maxIterations = 10000;
    let iterations = 0;
    
    while (runs.length < count && iterations < maxIterations) {
        current.setMinutes(current.getMinutes() + 1);
        iterations++;
        
        if (matchesCron(current, minField, hourField, domField, monthField, dowField)) {
            runs.push(new Date(current));
        }
    }
    
    return runs;
}

function matchesCron(date, minField, hourField, domField, monthField, dowField) {
    return matchesField(date.getMinutes(), minField, 0, 59) &&
           matchesField(date.getHours(), hourField, 0, 23) &&
           matchesField(date.getDate(), domField, 1, 31) &&
           matchesField(date.getMonth() + 1, monthField, 1, 12) &&
           matchesField(date.getDay(), dowField, 0, 6);
}

function matchesField(value, field, min, max) {
    if (field === '*') return true;
    
    // Step values: */n
    if (field.startsWith('*/')) {
        const step = parseInt(field.slice(2));
        return value % step === 0;
    }
    
    // Step from value: n/m
    if (field.includes('/') && !field.startsWith('*')) {
        const [start, step] = field.split('/').map(Number);
        return value >= start && (value - start) % step === 0;
    }
    
    // Ranges and lists
    const parts = field.split(',');
    for (const part of parts) {
        if (part.includes('-')) {
            const [start, end] = part.split('-').map(Number);
            if (value >= start && value <= end) return true;
        } else {
            if (parseInt(part) === value) return true;
        }
    }
    
    return false;
}

function formatDate(date) {
    const options = { 
        weekday: 'short', 
        month: 'short', 
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    };
    return date.toLocaleString('en-US', options);
}

// ============================================
// UI Updates
// ============================================

function updateResult(result, isError = false) {
    if (result) {
        resultValue.innerHTML = `<span style="color: ${isError ? '#ef4444' : 'var(--success)'}">${result}</span>`;
        copyBtn.disabled = isError;
        currentResult = isError ? '' : result;
    } else {
        resultValue.innerHTML = '<span class="placeholder">Enter a schedule above...</span>';
        copyBtn.disabled = true;
        currentResult = '';
    }
}

function updateNextRuns(cron) {
    try {
        const runs = getNextRuns(cron);
        if (runs.length > 0) {
            runsList.innerHTML = runs.map(r => `<li>${formatDate(r)}</li>`).join('');
        } else {
            runsList.innerHTML = '<li class="placeholder">Could not calculate runs</li>';
        }
    } catch (e) {
        runsList.innerHTML = '<li class="placeholder">--</li>';
    }
}

function handleEnglishInput() {
    const text = englishInput.value;
    const cron = englishToCron(text);
    
    if (cron) {
        updateResult(cron);
        updateNextRuns(cron);
    } else if (text.trim()) {
        updateResult("Couldn't parse that. Try something like 'every Monday at 9am'", true);
        runsList.innerHTML = '<li class="placeholder">--</li>';
    } else {
        updateResult(null);
        runsList.innerHTML = '<li class="placeholder">--</li>';
    }
}

function handleCronInput() {
    const cron = cronInput.value.trim();
    
    if (cron) {
        const english = cronToEnglish(cron);
        const isError = english.includes('Invalid');
        updateResult(english, isError);
        
        if (!isError) {
            updateNextRuns(cron);
        } else {
            runsList.innerHTML = '<li class="placeholder">--</li>';
        }
    } else {
        updateResult(null);
        runsList.innerHTML = '<li class="placeholder">--</li>';
    }
}

// ============================================
// Event Listeners
// ============================================

// Mode toggle
modeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        modeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        currentMode = btn.dataset.mode;
        
        if (currentMode === 'english') {
            englishMode.classList.remove('hidden');
            cronMode.classList.add('hidden');
            handleEnglishInput();
        } else {
            cronMode.classList.remove('hidden');
            englishMode.classList.add('hidden');
            handleCronInput();
        }
    });
});

// Input handlers
englishInput.addEventListener('input', handleEnglishInput);
cronInput.addEventListener('input', handleCronInput);

// Quick picks
quickPicks.forEach(pick => {
    pick.addEventListener('click', () => {
        englishInput.value = pick.dataset.value;
        handleEnglishInput();
    });
});

// Examples (click to use)
examples.forEach(ex => {
    ex.addEventListener('click', () => {
        const cronExpr = ex.querySelector('code').textContent;
        
        // Switch to cron mode and input
        modeButtons.forEach(b => b.classList.remove('active'));
        document.querySelector('[data-mode="cron"]').classList.add('active');
        englishMode.classList.add('hidden');
        cronMode.classList.remove('hidden');
        
        cronInput.value = cronExpr;
        currentMode = 'cron';
        handleCronInput();
    });
});

// Copy button
copyBtn.addEventListener('click', () => {
    if (currentResult) {
        navigator.clipboard.writeText(currentResult).then(() => {
            copyBtn.textContent = '✓ Copied!';
            copyBtn.classList.add('copied');
            setTimeout(() => {
                copyBtn.textContent = '📋 Copy';
                copyBtn.classList.remove('copied');
            }, 2000);
        });
    }
});

// Email signup (stores locally for demo)
const signupForm = document.getElementById('signup-form');
const signupMessage = document.getElementById('signup-message');

signupForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const email = document.getElementById('email').value;
    
    // Store locally (in real app, send to backend)
    const signups = JSON.parse(localStorage.getItem('cronmagic_signups') || '[]');
    if (!signups.includes(email)) {
        signups.push(email);
        localStorage.setItem('cronmagic_signups', JSON.stringify(signups));
    }
    
    signupMessage.textContent = '🎉 You\'re on the list! We\'ll notify you when Pro launches.';
    signupMessage.style.color = 'var(--success)';
    signupForm.reset();
});

// Feedback modal
const feedbackLink = document.getElementById('feedback-link');
const feedbackModal = document.getElementById('feedback-modal');
const closeModal = document.getElementById('close-modal');
const feedbackForm = document.getElementById('feedback-form');
const feedbackMessage = document.getElementById('feedback-message');

feedbackLink.addEventListener('click', (e) => {
    e.preventDefault();
    feedbackModal.classList.add('show');
});

closeModal.addEventListener('click', () => {
    feedbackModal.classList.remove('show');
});

feedbackModal.addEventListener('click', (e) => {
    if (e.target === feedbackModal) {
        feedbackModal.classList.remove('show');
    }
});

feedbackForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = document.getElementById('feedback-text').value;
    const email = document.getElementById('feedback-email').value;
    
    // Store locally (in real app, send to backend)
    const feedback = JSON.parse(localStorage.getItem('cronmagic_feedback') || '[]');
    feedback.push({ text, email, date: new Date().toISOString() });
    localStorage.setItem('cronmagic_feedback', JSON.stringify(feedback));
    
    feedbackMessage.textContent = '✨ Thanks for your feedback!';
    feedbackMessage.style.color = 'var(--success)';
    feedbackForm.reset();
    
    setTimeout(() => {
        feedbackModal.classList.remove('show');
        feedbackMessage.textContent = '';
    }, 2000);
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && feedbackModal.classList.contains('show')) {
        feedbackModal.classList.remove('show');
    }
});

// Initialize
handleEnglishInput();
