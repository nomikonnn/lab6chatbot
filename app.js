function toggleDescription(componentId) {
    const description = document.getElementById(componentId);
    const button = description.previousElementSibling.querySelector('.show-btn');

    const allDescriptions = document.querySelectorAll('.description');
    const allButtons = document.querySelectorAll('.show-btn');

    allDescriptions.forEach(desc => {
        if (desc.id !== componentId) desc.classList.remove('show');
    });

    allButtons.forEach(btn => {
        if (btn !== button) btn.textContent = 'Показать описание';
    });

    if (description.classList.contains('show')) {
        description.classList.remove('show');
        button.textContent = 'Показать описание';
    } else {
        description.classList.add('show');
        button.textContent = 'Скрыть описание';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const cards = document.querySelectorAll('.component-card');
    cards.forEach((card, index) => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(30px)';
        setTimeout(() => {
            card.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
            card.style.opacity = '1';
            card.style.transform = 'translateY(0)';
        }, index * 200);
    });

    document.addEventListener('click', function(event) {
        if (!event.target.closest('.component-card')) {
            const allDescriptions = document.querySelectorAll('.description');
            const allButtons = document.querySelectorAll('.show-btn');
            allDescriptions.forEach(desc => desc.classList.remove('show'));
            allButtons.forEach(btn => btn.textContent = 'Показать описание');
        }
    });

    const buttons = document.querySelectorAll('.show-btn');
    buttons.forEach(button => {
        button.addEventListener('mouseenter', () => button.style.transform = 'scale(1.05)');
        button.addEventListener('mouseleave', () => button.style.transform = 'scale(1)');
    });
});