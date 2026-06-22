// 底部導覽列：儀表板 / 庫存 / 掃描(中央凸起) / 神秘包。
import { NavLink } from "react-router-dom";
import "./bottomNav.css";

const items = [
  { to: "/", label: "儀表板", icon: "📊", end: true },
  { to: "/inventory", label: "庫存", icon: "🗂️", end: false },
  { to: "/scan", label: "掃描", icon: "📷", center: true, end: false },
  { to: "/packs", label: "神秘包", icon: "🎁", end: false },
];

export function BottomNav() {
  return (
    <nav className="bottom-nav">
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.end}
          className={({ isActive }) =>
            `nav-item${it.center ? " center" : ""}${isActive ? " active" : ""}`
          }
        >
          <span className="nav-icon">{it.icon}</span>
          <span className="nav-label">{it.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
