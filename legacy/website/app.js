const apiUrl = 'https://tekitinari.vercel.app';

// Letters for which buttons will be created
const letters = ['A', 'B', 'E', 'I', 'K', 'M', 'N', 'O', 'R', 'T', 'U', 'V', 'W'];

document.addEventListener('DOMContentLoaded', () => {
    // Create letter buttons
    const letterButtonsDiv = document.getElementById('letterButtons');
    //letters.forEach(letter => {
    //    const button = document.createElement('button');
    //    button.textContent = letter;
    //    button.addEventListener('click', () => fetchWordsByLetter(letter));
    //    letterButtonsDiv.appendChild(button);
    //});
    
    const list = document.createElement('ul');
    letters.forEach(letter => {
        const listItem = document.createElement('li');
        listItem.textContent = letter;
        listItem.addEventListener('click', () => fetchWordsByLetter(letter));
        list.appendChild(listItem);
    });
    letterButtonsDiv.appendChild(list);

    // Search word
    document.getElementById('searchWrdButton').addEventListener('click', async () => {
        const query = document.getElementById('searchInput').value.trim();
        if (!query) return;
        const response = await fetch(`${apiUrl}/searchwrd?query=${query}`);
        const words = await response.json();
        displayResults(words);
        document.getElementById('resultsPage').style.display = 'flex';
        document.getElementById('mainPage').style.display = 'none';
        document.getElementById('definitionPage').style.display = 'none';
    });
    
    // Search definition
    document.getElementById('searchDefButton').addEventListener('click', async () => {
        const query = document.getElementById('searchInput').value.trim();
        if (!query) return;
        const response = await fetch(`${apiUrl}/searchdef?query=${query}`);
        const words = await response.json();
        displayResults(words);
        document.getElementById('resultsPage').style.display = 'flex';
        document.getElementById('mainPage').style.display = 'none';
        document.getElementById('definitionPage').style.display = 'none';
    });

    // Back button functionality
    document.getElementById('backButton').addEventListener('click', () => {
        document.getElementById('resultsPage').style.display = 'none';
        document.getElementById('mainPage').style.display = 'flex';
        document.getElementById('definitionPage').style.display = 'none';
    });
    // Back to list button functionality
    document.getElementById('backListButton').addEventListener('click', () => {
        document.getElementById('resultsPage').style.display = 'flex';
        document.getElementById('mainPage').style.display = 'none';
        document.getElementById('definitionPage').style.display = 'none';
    });
});

async function fetchWordsByLetter(letter) {
    const response = await fetch(`${apiUrl}/words/${letter}`);
    const words = await response.json();
    displayResults(words);
}

function displayResults(words) {
    const resultsDiv = document.getElementById('results');
    resultsDiv.innerHTML = '';

    if (words.length === 0) {
        resultsDiv.innerHTML = '<p>No results found.</p>';
        return;
    }

    const list = document.createElement('ul');
    words.forEach(word => {
        const listItem = document.createElement('li');
        listItem.textContent = word;
        listItem.addEventListener('click', () => fetchDefinition2(word));
        list.appendChild(listItem);
    });

    resultsDiv.appendChild(list);

    // Switch to results page
    document.getElementById('mainPage').style.display = 'none';
    document.getElementById('resultsPage').style.display = 'flex';
    document.getElementById('definitionPage').style.display = 'none';
}

async function fetchDefinition(word) {
    const response = await fetch(`${apiUrl}/definition/${word}`);
    const definitions = await response.json();
    const resultsDiv = document.getElementById('results');

    resultsDiv.innerHTML = `<h2>${word}</h2>`;
    definitions.forEach(def => {
        const defParagraph = document.createElement('p');
        defParagraph.textContent = def;
        resultsDiv.appendChild(defParagraph);
    });
}

async function fetchDefinition2(word) {
    const encodedWord = encodeURIComponent(word);
    const response = await fetch(`${apiUrl}/definition/${encodedWord}`);
    const definitions = await response.json();
    const defDiv = document.getElementById('definition');

    defDiv.innerHTML = `<h2>${word}</h2>`;
    definitions.forEach(def => {
        const defParagraph = document.createElement('p');
        defParagraph.textContent = def;
        defDiv.appendChild(defParagraph);
    });

    
    // Switch to definition page
    document.getElementById('mainPage').style.display = 'none';
    document.getElementById('resultsPage').style.display = 'none';
    document.getElementById('definitionPage').style.display = 'flex';
}