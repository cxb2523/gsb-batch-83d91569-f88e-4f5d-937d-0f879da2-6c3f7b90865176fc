import {
  AlertTriangle,
  ArrowUp,
  Check,
  CheckCircle2,
  Copy,
  Fingerprint,
  Heart,
  Plus,
  Search,
  ShieldCheck,
  ShoppingCart,
  Trash2,
  Trophy,
  Upload,
  User,
  X,
  Zap,
  type LucideProps,
} from "lucide-react";
import { TROPHY_GRID, TROPHY_PIXELS } from "../pixelTrophy";

export const SearchIcon = (props: LucideProps) => <Search size={14} {...props} />;
export const ArrowUpIcon = (props: LucideProps) => <ArrowUp size={18} {...props} />;
export const CartIcon = (props: LucideProps) => <ShoppingCart size={16} {...props} />;
export const TrophyIcon = (props: LucideProps) => <Trophy size={11} {...props} />;
export const BoltIcon = (props: LucideProps) => <Zap size={14} {...props} />;
export const PlusIcon = (props: LucideProps) => <Plus size={14} {...props} />;
export const CheckIcon = (props: LucideProps) => <Check size={14} {...props} />;
export const TrashIcon = (props: LucideProps) => <Trash2 size={13} {...props} />;
export const XIcon = (props: LucideProps) => <X size={18} {...props} />;
export const FingerprintIcon = (props: LucideProps) => <Fingerprint size={14} {...props} />;
export const UserIcon = (props: LucideProps) => <User size={14} {...props} />;
export const CopyIcon = (props: LucideProps) => <Copy size={13} {...props} />;
export const UploadIcon = (props: LucideProps) => <Upload size={28} {...props} />;
export const ShieldCheckIcon = (props: LucideProps) => <ShieldCheck size={14} {...props} />;
export const CheckCircleIcon = (props: LucideProps) => <CheckCircle2 size={16} {...props} />;
export const WarningIcon = (props: LucideProps) => <AlertTriangle size={16} {...props} />;
export const HeartIcon = (props: LucideProps) => <Heart size={14} {...props} />;

// Logo del sitio: trofeo en pixel-art (ver pixelTrophy.ts). Usa currentColor
// para heredar el color de texto del contenedor (.brand .mark).
export const LogoMark = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox={`0 0 ${TROPHY_GRID} ${TROPHY_GRID}`} shapeRendering="crispEdges">
    {TROPHY_PIXELS.map(([x, y]) => (
      <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill="currentColor" />
    ))}
  </svg>
);

// Banderas para el selector de idioma: simplificadas (sin escudo/estrellas),
// inline en vez de emoji porque Windows no renderiza flag emoji como imagen.
export const SpainFlagIcon = ({ size = 16 }: { size?: number }) => (
  <svg
    className="flag-icon"
    style={{ width: size, height: size * 0.75, flexShrink: 0 }}
    viewBox="0 0 16 12"
    shapeRendering="crispEdges"
  >
    <rect width="16" height="12" fill="#AA151B" />
    <rect y="3" width="16" height="6" fill="#F1BF00" />
  </svg>
);

export const UsFlagIcon = ({ size = 16 }: { size?: number }) => (
  <svg
    className="flag-icon"
    style={{ width: size, height: size * 0.75, flexShrink: 0 }}
    viewBox="0 0 16 12"
    shapeRendering="crispEdges"
  >
    <rect width="16" height="12" fill="#fff" />
    <rect y="0" width="16" height="2" fill="#B22234" />
    <rect y="4" width="16" height="2" fill="#B22234" />
    <rect y="8" width="16" height="2" fill="#B22234" />
    <rect width="7" height="6" fill="#3C3B6E" />
  </svg>
);

export const PortugalFlagIcon = ({ size = 16 }: { size?: number }) => (
  <svg
    className="flag-icon"
    style={{ width: size, height: size * 0.75, flexShrink: 0 }}
    viewBox="0 0 16 12"
    shapeRendering="crispEdges"
  >
    <rect width="16" height="12" fill="#FF0000" />
    <rect width="6" height="12" fill="#006600" />
  </svg>
);

export const FranceFlagIcon = ({ size = 16 }: { size?: number }) => (
  <svg
    className="flag-icon"
    style={{ width: size, height: size * 0.75, flexShrink: 0 }}
    viewBox="0 0 16 12"
    shapeRendering="crispEdges"
  >
    <rect width="16" height="12" fill="#fff" />
    <rect width="6" height="12" fill="#002395" />
    <rect x="10" width="6" height="12" fill="#ED2939" />
  </svg>
);

// lucide-react no trae logos de marcas (Github incluido) -- mark oficial
// inline, misma convencion que LogoMark (currentColor, hereda del texto).
export const GithubIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.387.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.333-1.754-1.333-1.754-1.09-.744.083-.729.083-.729 1.205.084 1.84 1.237 1.84 1.237 1.07 1.834 2.807 1.304 3.492.997.108-.775.42-1.304.763-1.604-2.665-.303-5.467-1.332-5.467-5.93 0-1.31.467-2.38 1.235-3.22-.123-.303-.535-1.523.117-3.176 0 0 1.008-.322 3.3 1.23a11.5 11.5 0 013.003-.404c1.02.005 2.047.138 3.003.404 2.29-1.552 3.297-1.23 3.297-1.23.654 1.653.242 2.873.12 3.176.77.84 1.233 1.91 1.233 3.22 0 4.61-2.807 5.625-5.48 5.92.432.372.816 1.102.816 2.222 0 1.606-.015 2.896-.015 3.286 0 .32.216.694.825.576C20.565 21.795 24 17.298 24 12c0-6.63-5.37-12-12-12z" />
  </svg>
);
