export type Locale = "es" | "en" | "pt" | "fr";

const STORAGE_KEY = "ra-downloader-locale";

export const LANGUAGES: Array<{ code: Locale; label: string }> = [
  { code: "es", label: "Español" },
  { code: "en", label: "English" },
  { code: "pt", label: "Português" },
  { code: "fr", label: "Français" },
];

const es = {
  "topbar.searchPlaceholder": "Buscar por nombre o hash…",
  "topbar.verifyRom": "Verificar ROM",
  "topbar.connectRa": "Conectar RA",
  "topbar.openCart": "Abrir carrito",
  "topbar.langLabel": "Idioma",
  "common.backToTop": "Volver arriba",

  "footer.collaborate": "Colaborá con el repositorio",
  "footer.developedBy": "Desarrollado por",
  "footer.faqLegal": "FAQ y Aviso legal",

  "common.close": "Cerrar",
  "common.accept": "Aceptar",
  "common.download": "Descargar",
  "common.loading": "Cargando…",
  "common.noResults": "Sin resultados",
  "common.addToCart": "Agregar al carrito",
  "common.inCart": "En el carrito",
  "common.soon": "Próximamente",
  "common.backHome": "Volver al inicio",
  "common.unknownConsole": "Consola desconocida",
  "common.verifyingHash": "Verificando hash…",
  "common.hashNotFound": "No se encontró ese hash en la base de datos.",
  "common.hashVerifyFailed": "No se pudo verificar el hash.",

  "notice.title": "Antes de descargar",
  "notice.body1": "Nota: Para descargar, primero inicia sesión en ",
  "notice.body2":
    ". Los juegos no son de mi propiedad; todo el contenido está alojado en archive.org. Esta herramienta solo facilita enlaces de ROMs compatibles con RetroAchievements. Consulta la ",
  "notice.body3": ".",
  "notice.understood": "Entendido",

  "faq.title": "Preguntas frecuentes (FAQ)",
  "faq.q1": "¿Qué es este proyecto?",
  "faq.a1":
    "Esta herramienta ayuda a localizar y abrir enlaces de descarga de ROMs compatibles con los logros de RetroAchievements. No aloja ni distribuye archivos; solo redirige a contenidos públicos alojados en archive.org.",
  "faq.q2": "Inicio de sesión en archive.org",
  "faq.a2a": "Para descargar, primero inicia sesión en ",
  "faq.a2b": ". Sin sesión activa, las descargas pueden fallar o requerir verificación adicional.",
  "faq.q3": "¿De quién son los juegos/ROMs?",
  "faq.a3a": "Todos los archivos referenciados pertenecen a sus respectivos propietarios y están ",
  "faq.a3b": "almacenados en archive.org",
  "faq.a3c": ". Este proyecto no es propietario de ningún juego ni contenido y no los almacena.",
  "faq.q4": "Compatibilidad con RetroAchievements",
  "faq.a4":
    "Los enlaces se centran en ROMs que funcionan con los sets de logros de RetroAchievements. No se garantiza compatibilidad universal; sigue las recomendaciones de hashes y versiones publicadas por RetroAchievements.",
  "faq.q5": "¿La app descarga automáticamente?",
  "faq.a5": "No. Abrimos la URL de descarga en tu navegador para que completes el proceso en archive.org.",
  "faq.legalTitle": "Aviso legal",
  "faq.legal1": "Este proyecto no aloja, modifica, ni redistribuye ROMs. Solo facilita el acceso a enlaces públicos en archive.org.",
  "faq.legal2":
    "Los juegos, marcas y contenidos son propiedad de sus respectivos titulares. Su uso está sujeto a las leyes de derechos de autor aplicables en tu jurisdicción.",
  "faq.legal3a": "El autor/desarrollador ",
  "faq.legal3b": "no se responsabiliza",
  "faq.legal3c": " por el uso indebido de la herramienta ni por posibles infracciones de copyright por parte de los usuarios.",
  "faq.legal4":
    "El usuario es responsable de verificar que posee los derechos para descargar y usar cada archivo (por ejemplo, copias de seguridad de juegos que posee legalmente).",
  "faq.legal5": "RetroAchievements es una plataforma de terceros sin relación oficial con este proyecto.",
  "faq.tipsTitle": "Consejos",
  "faq.tip1": "Inicia sesión en archive.org antes de usar la búsqueda o abrir enlaces.",
  "faq.tip2": "Prefiere ROMs y hashes listados como compatibles en la página del juego de RetroAchievements.",
  "faq.tip3": "Respeta las leyes locales y los términos de uso de archive.org y RetroAchievements.",

  "cart.title": "Carrito de descarga",
  "cart.empty": "El carrito está vacío.",
  "cart.remove": "Quitar",
  "cart.exportStructure": "Estructura de exportación",
  "cart.flatRoot": "Raíz plana (todos juntos)",
  "cart.zipNote":
    'El empaquetado en ZIP con estructura de carpetas (RetroArch, OnionOS, Batocera) todavía no está disponible. Por ahora, "Descargar todo" abre cada archivo por separado.',

  "dropdown.searchConsole": "Buscar consola...",
  "dropdown.all": "Todo",

  "gamecard.versionRom": "Versión / ROM",
  "gamecard.noVersions": "Sin versiones",
  "gamecard.mirror": "Espejo de descarga",
  "gamecard.otherMirrors": "Otros espejos",
  "gamecard.copyHash": "Copiar hash MD5",
  "gamecard.hashCopied": "Hash copiado",
  "gamecard.viewOnRa": "Ver en RetroAchievements",

  "hasher.dropTitle": "Soltá tu ROM acá",
  "hasher.dropSub": "o hacé clic para explorar tu equipo",
  "hasher.selectFile": "Seleccionar archivo",
  "hasher.note":
    "Se calcula el hash MD5 en tu navegador, nunca se sube a ningún lado. Soporta .zip y las consolas de cartucho más comunes (CD/disco todavía no).",
  "hasher.discNote1": "¿Necesitás verificar discos (PS1, PS2, Saturn...)? Probá ",
  "hasher.discNote2": ", corre en tu PC con el RAHasher oficial.",
  "hasher.recognized": "Archivo reconocido",
  "hasher.found": "Archivo encontrado",
  "hasher.localFile": "Archivo local",
  "hasher.name": "Nombre:",
  "hasher.size": "Tamaño:",
  "hasher.hashMd5": "Hash MD5:",
  "hasher.game": "Juego:",
  "hasher.platform": "Plataforma:",
  "hasher.recognizedLabel": "Reconocido:",
  "hasher.yes": "Sí",
  "hasher.no": "No",
  "hasher.link": "Enlace:",
  "hasher.verified": "Verificado",
  "hasher.notVerified": "No verificado",
  "hasher.removeFile": "Quitar archivo",

  "games.title": "Buscar juegos",
  "games.indexedSuffix": "juegos indexados",
  "games.searchPlaceholder": "Nombre o hash…",
  "games.foundName": "Juego encontrado",
  "games.raRecognized": "reconocido por RA",
  "games.raNotRecognized": "no reconocido por RA",
  "games.linkVerified": "enlace verificado",
  "games.linkNotVerified": "enlace no verificado",
  "games.showLabel": "Mostrar",
  "games.noResults": "Sin resultados.",

  "ra.title": "Conectar RetroAchievements",
  "ra.body":
    'Conectá tu cuenta con tu propia Web API Key para traer tu lista "Want to Play" y ver qué juegos de ahí ya tenemos para descargar. La guardamos solo en tu navegador, nunca en nuestro servidor.',
  "ra.apiKeyLabel": "Web API Key",
  "ra.apiKeyPlaceholder": "Tu Web API Key de RetroAchievements",
  "ra.usernameLabel": "Usuario de RetroAchievements",
  "ra.usernamePlaceholder": "Tu nombre de usuario",
  "ra.getApiKeyHint": "¿No tenés una? Conseguila en ",
  "ra.getApiKeyLink": "retroachievements.org",
  "ra.connect": "Conectar",
  "ra.connecting": "Conectando…",
  "ra.connectedAs": "Conectado como",
  "ra.disconnect": "Desconectar",
  "ra.connectError": "No pudimos conectar: revisá tu API Key y usuario.",
  "ra.points": "Puntos",
  "ra.truePoints": "Puntos ponderados",

  "wtp.pill": "Mi Want to Play",
  "wtp.noResults": "No encontramos juegos de tu lista en nuestro catálogo.",
  "wtp.fetchError": "No pudimos traer tu lista de deseos. Intentá de nuevo.",

  "notfound.title": "Página no encontrada",
  "notfound.body": "La página que buscás no existe o se movió de lugar.",
};

const en: Record<keyof typeof es, string> = {
  "topbar.searchPlaceholder": "Search by name or hash…",
  "topbar.verifyRom": "Verify ROM",
  "topbar.connectRa": "Connect RA",
  "topbar.openCart": "Open cart",
  "topbar.langLabel": "Language",
  "common.backToTop": "Back to top",

  "footer.collaborate": "Contribute to the repo",
  "footer.developedBy": "Made by",
  "footer.faqLegal": "FAQ & legal notice",

  "common.close": "Close",
  "common.accept": "Accept",
  "common.download": "Download",
  "common.loading": "Loading…",
  "common.noResults": "No results",
  "common.addToCart": "Add to cart",
  "common.inCart": "In cart",
  "common.soon": "Soon",
  "common.backHome": "Back to home",
  "common.unknownConsole": "Unknown console",
  "common.verifyingHash": "Verifying hash…",
  "common.hashNotFound": "That hash wasn't found in the database.",
  "common.hashVerifyFailed": "Couldn't verify the hash.",

  "notice.title": "Before downloading",
  "notice.body1": "Note: to download, first log in to ",
  "notice.body2":
    ". These games aren't mine — everything is hosted on archive.org. This tool only provides links to RetroAchievements-compatible ROMs. See the ",
  "notice.body3": ".",
  "notice.understood": "Got it",

  "faq.title": "Frequently asked questions (FAQ)",
  "faq.q1": "What is this project?",
  "faq.a1":
    "This tool helps locate and open download links for ROMs compatible with RetroAchievements achievements. It doesn't host or distribute files; it only redirects to public content hosted on archive.org.",
  "faq.q2": "Logging in to archive.org",
  "faq.a2a": "To download, first log in to ",
  "faq.a2b": ". Without an active session, downloads may fail or require extra verification.",
  "faq.q3": "Who owns the games/ROMs?",
  "faq.a3a": "All referenced files belong to their respective owners and are ",
  "faq.a3b": "stored on archive.org",
  "faq.a3c": ". This project doesn't own and doesn't store any game or content.",
  "faq.q4": "RetroAchievements compatibility",
  "faq.a4":
    "Links focus on ROMs that work with RetroAchievements' achievement sets. Universal compatibility isn't guaranteed; follow the hash and version recommendations published by RetroAchievements.",
  "faq.q5": "Does the app download automatically?",
  "faq.a5": "No. We open the download URL in your browser so you can complete the process on archive.org.",
  "faq.legalTitle": "Legal notice",
  "faq.legal1": "This project doesn't host, modify, or redistribute ROMs. It only provides access to public links on archive.org.",
  "faq.legal2": "Games, trademarks, and content belong to their respective owners. Their use is subject to the copyright laws applicable in your jurisdiction.",
  "faq.legal3a": "The author/developer ",
  "faq.legal3b": "isn't responsible",
  "faq.legal3c": " for misuse of the tool or possible copyright infringement by users.",
  "faq.legal4": "Users are responsible for verifying they have the rights to download and use each file (for example, backups of games they legally own).",
  "faq.legal5": "RetroAchievements is a third-party platform with no official relationship to this project.",
  "faq.tipsTitle": "Tips",
  "faq.tip1": "Log in to archive.org before searching or opening links.",
  "faq.tip2": "Prefer ROMs and hashes listed as compatible on the game's RetroAchievements page.",
  "faq.tip3": "Follow local laws and the terms of use of archive.org and RetroAchievements.",

  "cart.title": "Download cart",
  "cart.empty": "Your cart is empty.",
  "cart.remove": "Remove",
  "cart.exportStructure": "Export structure",
  "cart.flatRoot": "Flat root (everything together)",
  "cart.zipNote":
    'ZIP packaging with folder structure (RetroArch, OnionOS, Batocera) isn\'t available yet. For now, "Download all" opens each file separately.',

  "dropdown.searchConsole": "Search console...",
  "dropdown.all": "All",

  "gamecard.versionRom": "Version / ROM",
  "gamecard.noVersions": "No versions",
  "gamecard.mirror": "Download mirror",
  "gamecard.otherMirrors": "Other mirrors",
  "gamecard.copyHash": "Copy MD5 hash",
  "gamecard.hashCopied": "Hash copied",
  "gamecard.viewOnRa": "View on RetroAchievements",

  "hasher.dropTitle": "Drop your ROM here",
  "hasher.dropSub": "or click to browse your computer",
  "hasher.selectFile": "Select file",
  "hasher.note":
    "The MD5 hash is calculated in your browser — it's never uploaded anywhere. Supports .zip and the most common cartridge consoles (CD/disc not yet).",
  "hasher.discNote1": "Need to verify discs (PS1, PS2, Saturn...)? Try ",
  "hasher.discNote2": ", it runs on your PC with the official RAHasher.",
  "hasher.recognized": "File recognized",
  "hasher.found": "File found",
  "hasher.localFile": "Local file",
  "hasher.name": "Name:",
  "hasher.size": "Size:",
  "hasher.hashMd5": "MD5 hash:",
  "hasher.game": "Game:",
  "hasher.platform": "Platform:",
  "hasher.recognizedLabel": "Recognized:",
  "hasher.yes": "Yes",
  "hasher.no": "No",
  "hasher.link": "Link:",
  "hasher.verified": "Verified",
  "hasher.notVerified": "Not verified",
  "hasher.removeFile": "Remove file",

  "games.title": "Search games",
  "games.indexedSuffix": "games indexed",
  "games.searchPlaceholder": "Name or hash…",
  "games.foundName": "Game found",
  "games.raRecognized": "recognized by RA",
  "games.raNotRecognized": "not recognized by RA",
  "games.linkVerified": "link verified",
  "games.linkNotVerified": "link not verified",
  "games.showLabel": "Show",
  "games.noResults": "No results.",

  "ra.title": "Connect RetroAchievements",
  "ra.body":
    'Connect your account with your own Web API Key to pull your "Want to Play" list and see which of those games we already have available to download. We only store it in your browser, never on our server.',
  "ra.apiKeyLabel": "Web API Key",
  "ra.apiKeyPlaceholder": "Your RetroAchievements Web API Key",
  "ra.usernameLabel": "RetroAchievements username",
  "ra.usernamePlaceholder": "Your username",
  "ra.getApiKeyHint": "Don't have one? Get it at ",
  "ra.getApiKeyLink": "retroachievements.org",
  "ra.connect": "Connect",
  "ra.connecting": "Connecting…",
  "ra.connectedAs": "Connected as",
  "ra.disconnect": "Disconnect",
  "ra.connectError": "Couldn't connect: check your API Key and username.",
  "ra.points": "Points",
  "ra.truePoints": "Weighted points",

  "wtp.pill": "My Want to Play",
  "wtp.noResults": "We didn't find any games from your list in our catalog.",
  "wtp.fetchError": "Couldn't load your want-to-play list. Try again.",

  "notfound.title": "Page not found",
  "notfound.body": "The page you're looking for doesn't exist or moved.",
};

const pt: Record<keyof typeof es, string> = {
  "topbar.searchPlaceholder": "Pesquisar por nome ou hash…",
  "topbar.verifyRom": "Verificar ROM",
  "topbar.connectRa": "Conectar RA",
  "topbar.openCart": "Abrir carrinho",
  "topbar.langLabel": "Idioma",
  "common.backToTop": "Voltar ao topo",

  "footer.collaborate": "Contribua com o repositório",
  "footer.developedBy": "Desenvolvido por",
  "footer.faqLegal": "FAQ e Aviso legal",

  "common.close": "Fechar",
  "common.accept": "Aceitar",
  "common.download": "Baixar",
  "common.loading": "Carregando…",
  "common.noResults": "Sem resultados",
  "common.addToCart": "Adicionar ao carrinho",
  "common.inCart": "No carrinho",
  "common.soon": "Em breve",
  "common.backHome": "Voltar ao início",
  "common.unknownConsole": "Console desconhecido",
  "common.verifyingHash": "Verificando hash…",
  "common.hashNotFound": "Esse hash não foi encontrado na base de dados.",
  "common.hashVerifyFailed": "Não foi possível verificar o hash.",

  "notice.title": "Antes de baixar",
  "notice.body1": "Nota: Para baixar, primeiro faça login em ",
  "notice.body2":
    ". Os jogos não são de minha propriedade; todo o conteúdo está hospedado no archive.org. Esta ferramenta apenas facilita links de ROMs compatíveis com o RetroAchievements. Consulte a ",
  "notice.body3": ".",
  "notice.understood": "Entendi",

  "faq.title": "Perguntas frequentes (FAQ)",
  "faq.q1": "O que é este projeto?",
  "faq.a1":
    "Esta ferramenta ajuda a localizar e abrir links de download de ROMs compatíveis com os troféus do RetroAchievements. Não hospeda nem distribui arquivos; apenas redireciona para conteúdos públicos hospedados no archive.org.",
  "faq.q2": "Login no archive.org",
  "faq.a2a": "Para baixar, primeiro faça login em ",
  "faq.a2b": ". Sem uma sessão ativa, os downloads podem falhar ou exigir verificação adicional.",
  "faq.q3": "De quem são os jogos/ROMs?",
  "faq.a3a": "Todos os arquivos referenciados pertencem aos seus respectivos proprietários e estão ",
  "faq.a3b": "armazenados no archive.org",
  "faq.a3c": ". Este projeto não é proprietário de nenhum jogo ou conteúdo e não os armazena.",
  "faq.q4": "Compatibilidade com o RetroAchievements",
  "faq.a4":
    "Os links se concentram em ROMs que funcionam com os conjuntos de troféus do RetroAchievements. A compatibilidade universal não é garantida; siga as recomendações de hashes e versões publicadas pelo RetroAchievements.",
  "faq.q5": "O aplicativo baixa automaticamente?",
  "faq.a5": "Não. Abrimos a URL de download no seu navegador para que você conclua o processo no archive.org.",
  "faq.legalTitle": "Aviso legal",
  "faq.legal1": "Este projeto não hospeda, modifica nem redistribui ROMs. Apenas facilita o acesso a links públicos no archive.org.",
  "faq.legal2":
    "Os jogos, marcas e conteúdos são propriedade de seus respectivos titulares. Seu uso está sujeito às leis de direitos autorais aplicáveis em sua jurisdição.",
  "faq.legal3a": "O autor/desenvolvedor ",
  "faq.legal3b": "não se responsabiliza",
  "faq.legal3c": " pelo uso indevido da ferramenta nem por possíveis infrações de direitos autorais por parte dos usuários.",
  "faq.legal4":
    "O usuário é responsável por verificar se possui os direitos para baixar e usar cada arquivo (por exemplo, cópias de segurança de jogos que possui legalmente).",
  "faq.legal5": "O RetroAchievements é uma plataforma de terceiros sem relação oficial com este projeto.",
  "faq.tipsTitle": "Dicas",
  "faq.tip1": "Faça login no archive.org antes de usar a busca ou abrir links.",
  "faq.tip2": "Prefira ROMs e hashes listados como compatíveis na página do jogo no RetroAchievements.",
  "faq.tip3": "Respeite as leis locais e os termos de uso do archive.org e do RetroAchievements.",

  "cart.title": "Carrinho de download",
  "cart.empty": "O carrinho está vazio.",
  "cart.remove": "Remover",
  "cart.exportStructure": "Estrutura de exportação",
  "cart.flatRoot": "Raiz plana (tudo junto)",
  "cart.zipNote":
    'O empacotamento em ZIP com estrutura de pastas (RetroArch, OnionOS, Batocera) ainda não está disponível. Por enquanto, "Baixar tudo" abre cada arquivo separadamente.',

  "dropdown.searchConsole": "Buscar console...",
  "dropdown.all": "Todos",

  "gamecard.versionRom": "Versão / ROM",
  "gamecard.noVersions": "Sem versões",
  "gamecard.mirror": "Espelho de download",
  "gamecard.otherMirrors": "Outros espelhos",
  "gamecard.copyHash": "Copiar hash MD5",
  "gamecard.hashCopied": "Hash copiado",
  "gamecard.viewOnRa": "Ver no RetroAchievements",

  "hasher.dropTitle": "Solte sua ROM aqui",
  "hasher.dropSub": "ou clique para explorar seu computador",
  "hasher.selectFile": "Selecionar arquivo",
  "hasher.note":
    "O hash MD5 é calculado no seu navegador, nunca é enviado a lugar nenhum. Suporta .zip e os consoles de cartucho mais comuns (CD/disco ainda não).",
  "hasher.discNote1": "Precisa verificar discos (PS1, PS2, Saturn...)? Experimente ",
  "hasher.discNote2": ", funciona no seu PC com o RAHasher oficial.",
  "hasher.recognized": "Arquivo reconhecido",
  "hasher.found": "Arquivo encontrado",
  "hasher.localFile": "Arquivo local",
  "hasher.name": "Nome:",
  "hasher.size": "Tamanho:",
  "hasher.hashMd5": "Hash MD5:",
  "hasher.game": "Jogo:",
  "hasher.platform": "Plataforma:",
  "hasher.recognizedLabel": "Reconhecido:",
  "hasher.yes": "Sim",
  "hasher.no": "Não",
  "hasher.link": "Link:",
  "hasher.verified": "Verificado",
  "hasher.notVerified": "Não verificado",
  "hasher.removeFile": "Remover arquivo",

  "games.title": "Buscar jogos",
  "games.indexedSuffix": "jogos indexados",
  "games.searchPlaceholder": "Nome ou hash…",
  "games.foundName": "Jogo encontrado",
  "games.raRecognized": "reconhecido pela RA",
  "games.raNotRecognized": "não reconhecido pela RA",
  "games.linkVerified": "link verificado",
  "games.linkNotVerified": "link não verificado",
  "games.showLabel": "Mostrar",
  "games.noResults": "Sem resultados.",

  "ra.title": "Conectar RetroAchievements",
  "ra.body":
    'Conecte sua conta com sua própria Web API Key para trazer sua lista "Want to Play" e ver quais desses jogos já temos disponíveis para baixar. Guardamos isso só no seu navegador, nunca em nosso servidor.',
  "ra.apiKeyLabel": "Web API Key",
  "ra.apiKeyPlaceholder": "Sua Web API Key do RetroAchievements",
  "ra.usernameLabel": "Usuário do RetroAchievements",
  "ra.usernamePlaceholder": "Seu nome de usuário",
  "ra.getApiKeyHint": "Não tem uma? Consiga em ",
  "ra.getApiKeyLink": "retroachievements.org",
  "ra.connect": "Conectar",
  "ra.connecting": "Conectando…",
  "ra.connectedAs": "Conectado como",
  "ra.disconnect": "Desconectar",
  "ra.connectError": "Não conseguimos conectar: confira sua API Key e usuário.",
  "ra.points": "Pontos",
  "ra.truePoints": "Pontos ponderados",

  "wtp.pill": "Minha Want to Play",
  "wtp.noResults": "Não encontramos jogos da sua lista em nosso catálogo.",
  "wtp.fetchError": "Não conseguimos carregar sua lista de desejos. Tente novamente.",

  "notfound.title": "Página não encontrada",
  "notfound.body": "A página que você procura não existe ou foi movida.",
};

const fr: Record<keyof typeof es, string> = {
  "topbar.searchPlaceholder": "Rechercher par nom ou hash…",
  "topbar.verifyRom": "Vérifier la ROM",
  "topbar.connectRa": "Connecter RA",
  "topbar.openCart": "Ouvrir le panier",
  "topbar.langLabel": "Langue",
  "common.backToTop": "Retour en haut",

  "footer.collaborate": "Contribuer au dépôt",
  "footer.developedBy": "Développé par",
  "footer.faqLegal": "FAQ et mentions légales",

  "common.close": "Fermer",
  "common.accept": "Accepter",
  "common.download": "Télécharger",
  "common.loading": "Chargement…",
  "common.noResults": "Aucun résultat",
  "common.addToCart": "Ajouter au panier",
  "common.inCart": "Dans le panier",
  "common.soon": "Bientôt",
  "common.backHome": "Retour à l'accueil",
  "common.unknownConsole": "Console inconnue",
  "common.verifyingHash": "Vérification du hash…",
  "common.hashNotFound": "Ce hash n'a pas été trouvé dans la base de données.",
  "common.hashVerifyFailed": "Impossible de vérifier le hash.",

  "notice.title": "Avant de télécharger",
  "notice.body1": "Remarque : pour télécharger, connectez-vous d'abord sur ",
  "notice.body2":
    ". Ces jeux ne m'appartiennent pas ; tout le contenu est hébergé sur archive.org. Cet outil ne fait que fournir des liens vers des ROMs compatibles avec RetroAchievements. Consultez la ",
  "notice.body3": ".",
  "notice.understood": "J'ai compris",

  "faq.title": "Questions fréquentes (FAQ)",
  "faq.q1": "Qu'est-ce que ce projet ?",
  "faq.a1":
    "Cet outil aide à localiser et ouvrir des liens de téléchargement de ROMs compatibles avec les succès de RetroAchievements. Il n'héberge ni ne distribue de fichiers ; il redirige uniquement vers du contenu public hébergé sur archive.org.",
  "faq.q2": "Connexion à archive.org",
  "faq.a2a": "Pour télécharger, connectez-vous d'abord sur ",
  "faq.a2b": ". Sans session active, les téléchargements peuvent échouer ou nécessiter une vérification supplémentaire.",
  "faq.q3": "À qui appartiennent les jeux/ROMs ?",
  "faq.a3a": "Tous les fichiers référencés appartiennent à leurs propriétaires respectifs et sont ",
  "faq.a3b": "stockés sur archive.org",
  "faq.a3c": ". Ce projet ne possède ni ne stocke aucun jeu ou contenu.",
  "faq.q4": "Compatibilité avec RetroAchievements",
  "faq.a4":
    "Les liens se concentrent sur les ROMs compatibles avec les ensembles de succès de RetroAchievements. La compatibilité universelle n'est pas garantie ; suivez les recommandations de hash et de version publiées par RetroAchievements.",
  "faq.q5": "L'application télécharge-t-elle automatiquement ?",
  "faq.a5": "Non. Nous ouvrons l'URL de téléchargement dans votre navigateur afin que vous puissiez terminer le processus sur archive.org.",
  "faq.legalTitle": "Mentions légales",
  "faq.legal1": "Ce projet n'héberge, ne modifie ni ne redistribue de ROMs. Il facilite uniquement l'accès à des liens publics sur archive.org.",
  "faq.legal2":
    "Les jeux, marques et contenus appartiennent à leurs titulaires respectifs. Leur utilisation est soumise aux lois sur le droit d'auteur applicables dans votre juridiction.",
  "faq.legal3a": "L'auteur/développeur ",
  "faq.legal3b": "n'est pas responsable",
  "faq.legal3c": " de l'utilisation abusive de l'outil ni des éventuelles infractions au droit d'auteur commises par les utilisateurs.",
  "faq.legal4":
    "L'utilisateur est responsable de vérifier qu'il possède les droits pour télécharger et utiliser chaque fichier (par exemple, des sauvegardes de jeux qu'il possède légalement).",
  "faq.legal5": "RetroAchievements est une plateforme tierce sans relation officielle avec ce projet.",
  "faq.tipsTitle": "Conseils",
  "faq.tip1": "Connectez-vous à archive.org avant d'utiliser la recherche ou d'ouvrir des liens.",
  "faq.tip2": "Préférez les ROMs et hashs listés comme compatibles sur la page du jeu sur RetroAchievements.",
  "faq.tip3": "Respectez les lois locales et les conditions d'utilisation d'archive.org et de RetroAchievements.",

  "cart.title": "Panier de téléchargement",
  "cart.empty": "Le panier est vide.",
  "cart.remove": "Retirer",
  "cart.exportStructure": "Structure d'export",
  "cart.flatRoot": "Racine plate (tout ensemble)",
  "cart.zipNote":
    "L'empaquetage en ZIP avec structure de dossiers (RetroArch, OnionOS, Batocera) n'est pas encore disponible. Pour l'instant, « Tout télécharger » ouvre chaque fichier séparément.",

  "dropdown.searchConsole": "Rechercher une console...",
  "dropdown.all": "Tous",

  "gamecard.versionRom": "Version / ROM",
  "gamecard.noVersions": "Aucune version",
  "gamecard.mirror": "Miroir de téléchargement",
  "gamecard.otherMirrors": "Autres miroirs",
  "gamecard.copyHash": "Copier le hash MD5",
  "gamecard.hashCopied": "Hash copié",
  "gamecard.viewOnRa": "Voir sur RetroAchievements",

  "hasher.dropTitle": "Déposez votre ROM ici",
  "hasher.dropSub": "ou cliquez pour parcourir votre ordinateur",
  "hasher.selectFile": "Sélectionner un fichier",
  "hasher.note":
    "Le hash MD5 est calculé dans votre navigateur, il n'est jamais envoyé nulle part. Prend en charge .zip et les consoles à cartouche les plus courantes (CD/disque pas encore).",
  "hasher.discNote1": "Besoin de vérifier des disques (PS1, PS2, Saturn...) ? Essayez ",
  "hasher.discNote2": ", il fonctionne sur votre PC avec le RAHasher officiel.",
  "hasher.recognized": "Fichier reconnu",
  "hasher.found": "Fichier trouvé",
  "hasher.localFile": "Fichier local",
  "hasher.name": "Nom :",
  "hasher.size": "Taille :",
  "hasher.hashMd5": "Hash MD5 :",
  "hasher.game": "Jeu :",
  "hasher.platform": "Plateforme :",
  "hasher.recognizedLabel": "Reconnu :",
  "hasher.yes": "Oui",
  "hasher.no": "Non",
  "hasher.link": "Lien :",
  "hasher.verified": "Vérifié",
  "hasher.notVerified": "Non vérifié",
  "hasher.removeFile": "Retirer le fichier",

  "games.title": "Rechercher des jeux",
  "games.indexedSuffix": "jeux indexés",
  "games.searchPlaceholder": "Nom ou hash…",
  "games.foundName": "Jeu trouvé",
  "games.raRecognized": "reconnu par RA",
  "games.raNotRecognized": "non reconnu par RA",
  "games.linkVerified": "lien vérifié",
  "games.linkNotVerified": "lien non vérifié",
  "games.showLabel": "Afficher",
  "games.noResults": "Aucun résultat.",

  "ra.title": "Connecter RetroAchievements",
  "ra.body":
    "Connectez votre compte avec votre propre clé Web API pour récupérer votre liste « Want to Play » et voir lesquels de ces jeux sont déjà disponibles chez nous. On la stocke seulement dans votre navigateur, jamais sur notre serveur.",
  "ra.apiKeyLabel": "Clé Web API",
  "ra.apiKeyPlaceholder": "Votre clé Web API RetroAchievements",
  "ra.usernameLabel": "Nom d'utilisateur RetroAchievements",
  "ra.usernamePlaceholder": "Votre nom d'utilisateur",
  "ra.getApiKeyHint": "Vous n'en avez pas ? Récupérez-la sur ",
  "ra.getApiKeyLink": "retroachievements.org",
  "ra.connect": "Connecter",
  "ra.connecting": "Connexion…",
  "ra.connectedAs": "Connecté en tant que",
  "ra.disconnect": "Déconnecter",
  "ra.connectError": "Connexion impossible : vérifiez votre clé API et votre nom d'utilisateur.",
  "ra.points": "Points",
  "ra.truePoints": "Points pondérés",

  "wtp.pill": "Ma liste Want to Play",
  "wtp.noResults": "Aucun jeu de votre liste n'a été trouvé dans notre catalogue.",
  "wtp.fetchError": "Impossible de récupérer votre liste. Réessayez.",

  "notfound.title": "Page introuvable",
  "notfound.body": "La page que vous recherchez n'existe pas ou a été déplacée.",
};

const dict = { es, en, pt, fr };
export type Key = keyof typeof es;

let current: Locale = "es";
const listeners = new Set<(l: Locale) => void>();

export function getLocale(): Locale {
  return current;
}

export function initLocale(): Locale {
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "es" || stored === "en" || stored === "pt" || stored === "fr") current = stored;
  }
  return current;
}

export function setLocale(l: Locale): void {
  current = l;
  if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, l);
  listeners.forEach((fn) => fn(l));
}

export function subscribe(fn: (l: Locale) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function t(key: Key, locale: Locale = current): string {
  return dict[locale][key];
}

export function gamesSelected(n: number, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return `${n} juego${n === 1 ? "" : "s"} seleccionado${n === 1 ? "" : "s"}`;
    case "pt":
      return `${n} jogo${n === 1 ? "" : "s"} selecionado${n === 1 ? "" : "s"}`;
    case "fr":
      return `${n} jeu${n === 1 ? "" : "x"} sélectionné${n === 1 ? "" : "s"}`;
    default:
      return `${n} game${n === 1 ? "" : "s"} selected`;
  }
}

export function downloadAllLabel(n: number, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return `Descargar todo (${n})`;
    case "pt":
      return `Baixar tudo (${n})`;
    case "fr":
      return `Tout télécharger (${n})`;
    default:
      return `Download all (${n})`;
  }
}

export function downloadingToast(n: number, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return `Descargando ${n} juego${n === 1 ? "" : "s"}…`;
    case "pt":
      return `Baixando ${n} jogo${n === 1 ? "" : "s"}…`;
    case "fr":
      return `Téléchargement de ${n} jeu${n === 1 ? "" : "x"}…`;
    default:
      return `Downloading ${n} game${n === 1 ? "" : "s"}…`;
  }
}

export function resultsCount(n: number, filter: string, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return `${n} juegos${filter ? ` en ${filter}` : ""}`;
    case "pt":
      return `${n} jogos${filter ? ` em ${filter}` : ""}`;
    case "fr":
      return `${n} jeux${filter ? ` dans ${filter}` : ""}`;
    default:
      return `${n} games${filter ? ` in ${filter}` : ""}`;
  }
}

export function downloadingNamed(name: string | undefined, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return name ? `Descargando ${name}…` : "Descargando juego…";
    case "pt":
      return name ? `Baixando ${name}…` : "Baixando jogo…";
    case "fr":
      return name ? `Téléchargement de ${name}…` : "Téléchargement du jeu…";
    default:
      return name ? `Downloading ${name}…` : "Downloading game…";
  }
}

export function wtpFoundCount(total: number, requested: number, locale: Locale = current): string {
  switch (locale) {
    case "es":
      return `Encontramos ${total} de ${requested} juego${requested === 1 ? "" : "s"} en nuestro catálogo.`;
    case "pt":
      return `Encontramos ${total} de ${requested} jogo${requested === 1 ? "" : "s"} em nosso catálogo.`;
    case "fr":
      return `Nous avons trouvé ${total} jeu${requested === 1 ? "" : "x"} sur ${requested} dans notre catalogue.`;
    default:
      return `Found ${total} of ${requested} game${requested === 1 ? "" : "s"} in our catalog.`;
  }
}
