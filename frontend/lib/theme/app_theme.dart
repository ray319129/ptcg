// 設計系統 Design Tokens — Card拍拍 風格「Utility-First Fintech × Gamified Collection」
//
// 提供 Dark Mode First 的完整 ThemeData，並附 Light Mode 替代。
// 所有顏色、字體、卡面形狀、文字樣式集中定義，元件層只引用語意 token，
// 不再散落硬編碼色碼。
//
// 依賴 (pubspec.yaml)：
//   google_fonts: ^6.x   // 動態載入 Inter / JetBrains Mono
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// 品牌色彩與語意色票（不隨亮暗模式變動的原始色）。
class AppColors {
  AppColors._();

  // ---- 品牌 / 稀有度峰值 ----
  static const Color brandGold = Color(0xFFFFCB05); // Pokemon Gold

  // ---- Dark Mode 基底 ----
  static const Color bgBase = Color(0xFF121214); // Deep Charcoal，抗反光
  static const Color surfaceCard = Color(0xFF1E1E24); // Elevated Grey
  static const Color surfaceCardHigh = Color(0xFF26262E); // 更高層級卡面
  static const Color divider = Color(0xFF2C2C34);

  // ---- 漲跌語意色 ----
  static const Color upTrend = Color(0xFF34C759); // Neon Mint，漲價 / 獲利
  static const Color downTrend = Color(0xFFFF3B30); // Crimson，跌價

  // ---- 文字 ----
  static const Color textPrimary = Color(0xFFF5F5F7);
  static const Color textSecondary = Color(0xFF9A9AA2);
  static const Color textOnGold = Color(0xFF121214);

  // ---- Light Mode 基底 ----
  static const Color lightBg = Color(0xFFF7F7F9);
  static const Color lightSurface = Color(0xFFFFFFFF);
  static const Color lightTextPrimary = Color(0xFF1B1B1F);
  static const Color lightTextSecondary = Color(0xFF6B6B73);

  // ---- 稀有度色（HUD / badge 用）----
  static const Map<String, Color> rarity = {
    'SAR': brandGold,
    'UR': Color(0xFFFF7AD9),
    'SR': Color(0xFFB388FF),
    'AR': Color(0xFF64B5F6),
    'RR': Color(0xFF4DD0E1),
    'R': Color(0xFF90A4AE),
    'U': Color(0xFF78909C),
    'C': Color(0xFF607D8B),
  };
}

/// 間距、圓角、動畫等 layout token。
class AppDimens {
  AppDimens._();

  static const double radiusSm = 8;
  static const double radiusMd = 14;
  static const double radiusLg = 20;
  static const double radiusPill = 999;

  static const double gap4 = 4;
  static const double gap8 = 8;
  static const double gap12 = 12;
  static const double gap16 = 16;
  static const double gap24 = 24;

  static const Duration motionFast = Duration(milliseconds: 120);
  static const Duration motionBase = Duration(milliseconds: 240);
}

/// 主題工廠。
class AppTheme {
  AppTheme._();

  /// 等寬字（TCG 代碼 SV8a 217/187 SAR 用，確保對齊可掃讀）。
  static TextStyle mono({
    double size = 14,
    FontWeight weight = FontWeight.w500,
    Color? color,
  }) {
    return GoogleFonts.jetBrainsMono(
      fontSize: size,
      fontWeight: weight,
      letterSpacing: 0.5,
      color: color,
    );
  }

  static TextTheme _textTheme(Color primary, Color secondary) {
    final base = GoogleFonts.interTextTheme();
    return base.copyWith(
      // Hero 數字（資產淨值）
      displaySmall: GoogleFonts.inter(
        fontSize: 34, fontWeight: FontWeight.w800, color: primary,
        letterSpacing: -0.5,
      ),
      headlineSmall: GoogleFonts.inter(
        fontSize: 22, fontWeight: FontWeight.w700, color: primary),
      titleMedium: GoogleFonts.inter(
        fontSize: 16, fontWeight: FontWeight.w600, color: primary),
      bodyMedium: GoogleFonts.inter(
        fontSize: 14, fontWeight: FontWeight.w400, color: primary),
      bodySmall: GoogleFonts.inter(
        fontSize: 12, fontWeight: FontWeight.w400, color: secondary),
      labelLarge: GoogleFonts.inter(
        fontSize: 14, fontWeight: FontWeight.w600, color: primary),
    );
  }

  static CardThemeData _cardTheme(Color surface) => CardThemeData(
        color: surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimens.radiusMd),
        ),
      );

  /// Dark Mode（預設）。
  static ThemeData get dark {
    final scheme = const ColorScheme.dark(
      primary: AppColors.brandGold,
      onPrimary: AppColors.textOnGold,
      secondary: AppColors.upTrend,
      surface: AppColors.surfaceCard,
      onSurface: AppColors.textPrimary,
      error: AppColors.downTrend,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppColors.bgBase,
      colorScheme: scheme,
      dividerColor: AppColors.divider,
      textTheme: _textTheme(AppColors.textPrimary, AppColors.textSecondary),
      cardTheme: _cardTheme(AppColors.surfaceCard),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.bgBase,
        elevation: 0,
        foregroundColor: AppColors.textPrimary,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.brandGold,
          foregroundColor: AppColors.textOnGold,
          textStyle: GoogleFonts.inter(fontWeight: FontWeight.w700),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppDimens.radiusPill),
          ),
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.surfaceCardHigh,
        labelStyle: mono(size: 12, color: AppColors.textPrimary),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppDimens.radiusSm),
        ),
        side: BorderSide.none,
      ),
    );
  }

  /// Light Mode 替代。
  static ThemeData get light {
    final scheme = const ColorScheme.light(
      primary: AppColors.brandGold,
      onPrimary: AppColors.textOnGold,
      secondary: AppColors.upTrend,
      surface: AppColors.lightSurface,
      onSurface: AppColors.lightTextPrimary,
      error: AppColors.downTrend,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: AppColors.lightBg,
      colorScheme: scheme,
      textTheme:
          _textTheme(AppColors.lightTextPrimary, AppColors.lightTextSecondary),
      cardTheme: _cardTheme(AppColors.lightSurface),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.lightBg,
        elevation: 0,
        foregroundColor: AppColors.lightTextPrimary,
      ),
    );
  }
}

/// 漲跌方向 → 色彩的語意輔助。
extension TrendColor on num {
  Color get trendColor =>
      this >= 0 ? AppColors.upTrend : AppColors.downTrend;
  String get trendSign => this >= 0 ? '+' : '';
}
