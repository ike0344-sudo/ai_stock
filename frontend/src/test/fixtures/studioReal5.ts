// 실제 서버 응답(2026-09-26, 프리셋 new_high_20 · 2024-01~2026-08 · 상위 60종목 · 변수 n×vol_mult 60조합)에서 뽑은 고정 값.
// 검증 결과 하위 구조(summary.optimize·walkforward·holdout, folds)는 타입을 붙여 선언해 컴파일이 실제 응답과 맞는지 검사한다.
import type { FoldsFile, GridRow, HoldoutSummary, OptimizeSummary, RunDetail, WalkforwardSummary } from '@/types/studio'

export const realOptSummary: OptimizeSummary = {
 "objective": "sharpe",
 "min_trades": 20,
 "n_combos": 60,
 "n_valid": 60,
 "n_invalid": 0,
 "segments": {
  "is": [
   "2024-01-02",
   "2025-07-01",
   363
  ],
  "oos": [
   "2025-07-02",
   "2026-02-20",
   156
  ],
  "holdout": [
   "2026-02-23",
   "2026-08-31",
   129
  ]
 },
 "selected": {
  "params": {
   "n": 60,
   "vol_mult": 3.0,
   "exit_n": 7
  },
  "is": {
   "total_return_pct": -15.933326074833754,
   "cagr_pct": -11.351219458211038,
   "max_drawdown_pct": 65.77053171615029,
   "mdd_duration_bars": 254,
   "volatility_pct": 46.65619152749642,
   "sharpe": -0.031039073885631596,
   "sortino": -0.052628164766032964,
   "calmar": -0.17258822700719764,
   "num_trades": 462,
   "win_rate_pct": 31.16883116883117,
   "profit_factor": 0.9063510351421539,
   "avg_win_pct": 11.828341387613502,
   "avg_loss_pct": -5.913548719819815,
   "expectancy_pct": -0.38360894607436563,
   "max_consec_losses": 22
  },
  "oos": {
   "total_return_pct": 81.41408316642898,
   "cagr_pct": 161.72978661115712,
   "max_drawdown_pct": 27.418492150354425,
   "mdd_duration_bars": 69,
   "volatility_pct": 42.95679223178693,
   "sharpe": 2.455260979849456,
   "sortino": 4.295723359114451,
   "calmar": 5.898566037996606,
   "num_trades": 175,
   "win_rate_pct": 40.0,
   "profit_factor": 1.7772065546757043,
   "avg_win_pct": 16.021537844007057,
   "avg_loss_pct": -6.145102486303017,
   "expectancy_pct": 2.721553645821012,
   "max_consec_losses": 10
  },
  "is_objective": -0.031039073885631596,
  "oos_objective": 2.455260979849456,
  "selected_by": "IS 목표값만 사용"
 },
 "neighbor_stability": {
  "best": -0.031039073885631596,
  "n_neighbors": 3,
  "n_invalid": 0,
  "median": -0.2370396602510612,
  "ratio": null,
  "warn": true,
  "reason": "최고 목표값이 0 이하라 비율이 뜻이 없다"
 },
 "criteria_on_oos": [
  {
   "metric": "sharpe",
   "threshold": 0.5,
   "direction": "min",
   "value": 2.455260979849456,
   "passed": true,
   "note": null
  },
  {
   "metric": "max_drawdown_pct",
   "threshold": 30.0,
   "direction": "max",
   "value": 27.418492150354425,
   "passed": true,
   "note": null
  }
 ],
 "selection_note": "조합마다 최적화 구간 전체를 1회 실행해 곡선을 IS/OOS 로 잘랐다(경계에 걸친 보유는 이어짐)"
}

export const realGrid: GridRow[] = [
 {
  "n": 10,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.4646273085710609,
  "is_trades": 398,
  "is_return_pct": -33.084278078277954,
  "is_mdd_pct": 60.86322878178543,
  "oos_sharpe": 0.8339576482082781,
  "oos_trades": 167,
  "oos_return_pct": 18.79470192749244,
  "oos_mdd_pct": 25.130276795171735,
  "rank_is": 14,
  "selected": false
 },
 {
  "n": 10,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.9016765081149919,
  "is_trades": 439,
  "is_return_pct": -47.8555349216764,
  "is_mdd_pct": 67.02934088726506,
  "oos_sharpe": 1.5200519642846302,
  "oos_trades": 159,
  "oos_return_pct": 47.35118292980924,
  "oos_mdd_pct": 18.97271117583236,
  "rank_is": 52,
  "selected": false
 },
 {
  "n": 10,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7311005143427941,
  "is_trades": 420,
  "is_return_pct": -43.398327203174766,
  "is_mdd_pct": 70.520456484674,
  "oos_sharpe": 0.921303985935264,
  "oos_trades": 161,
  "oos_return_pct": 20.997546018517376,
  "oos_mdd_pct": 27.893613170360286,
  "rank_is": 40,
  "selected": false
 },
 {
  "n": 10,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8677175474128228,
  "is_trades": 461,
  "is_return_pct": -50.21333755901184,
  "is_mdd_pct": 75.00739294553465,
  "oos_sharpe": 1.397612054158576,
  "oos_trades": 157,
  "oos_return_pct": 40.94735816895847,
  "oos_mdd_pct": 24.22895778191785,
  "rank_is": 48,
  "selected": false
 },
 {
  "n": 10,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6723978270143104,
  "is_trades": 460,
  "is_return_pct": -43.99140961074961,
  "is_mdd_pct": 76.0157316604834,
  "oos_sharpe": 1.9349247371678244,
  "oos_trades": 165,
  "oos_return_pct": 62.46935185297164,
  "oos_mdd_pct": 18.0924400408494,
  "rank_is": 34,
  "selected": false
 },
 {
  "n": 20,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5969204301928428,
  "is_trades": 423,
  "is_return_pct": -38.97334692444899,
  "is_mdd_pct": 64.3935468596324,
  "oos_sharpe": -0.1167923791242365,
  "oos_trades": 178,
  "oos_return_pct": -8.887374969664696,
  "oos_mdd_pct": 27.303009044062133,
  "rank_is": 29,
  "selected": false
 },
 {
  "n": 20,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.323629682841702,
  "is_trades": 429,
  "is_return_pct": -59.59858808179103,
  "is_mdd_pct": 75.05606537275766,
  "oos_sharpe": 0.724219822893528,
  "oos_trades": 178,
  "oos_return_pct": 15.657786820611141,
  "oos_mdd_pct": 31.76608670365416,
  "rank_is": 59,
  "selected": false
 },
 {
  "n": 20,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.9085287817806054,
  "is_trades": 432,
  "is_return_pct": -49.593059326829035,
  "is_mdd_pct": 73.28048674398482,
  "oos_sharpe": 1.7178411399472102,
  "oos_trades": 166,
  "oos_return_pct": 55.70909114921005,
  "oos_mdd_pct": 20.344009978264932,
  "rank_is": 53,
  "selected": false
 },
 {
  "n": 20,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.748386843793915,
  "is_trades": 457,
  "is_return_pct": -45.93274883396656,
  "is_mdd_pct": 72.03947771419672,
  "oos_sharpe": 1.8114914498491652,
  "oos_trades": 184,
  "oos_return_pct": 60.54917552871031,
  "oos_mdd_pct": 23.902008925062578,
  "rank_is": 41,
  "selected": false
 },
 {
  "n": 20,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.21121958093106102,
  "is_trades": 469,
  "is_return_pct": -24.604330462349733,
  "is_mdd_pct": 64.61250501445686,
  "oos_sharpe": 1.9363427449532546,
  "oos_trades": 180,
  "oos_return_pct": 64.16774140279703,
  "oos_mdd_pct": 24.429401634024504,
  "rank_is": 7,
  "selected": false
 },
 {
  "n": 30,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.46972976546987255,
  "is_trades": 430,
  "is_return_pct": -35.23670697302897,
  "is_mdd_pct": 65.05886293300749,
  "oos_sharpe": 0.7420866653452493,
  "oos_trades": 162,
  "oos_return_pct": 15.90489439256264,
  "oos_mdd_pct": 19.335565128135634,
  "rank_is": 15,
  "selected": false
 },
 {
  "n": 30,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.40878581502436157,
  "is_trades": 424,
  "is_return_pct": -31.21622129743129,
  "is_mdd_pct": 60.220868766164195,
  "oos_sharpe": 0.3616931628703566,
  "oos_trades": 160,
  "oos_return_pct": 3.851127920038455,
  "oos_mdd_pct": 30.518910581344382,
  "rank_is": 13,
  "selected": false
 },
 {
  "n": 30,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8225476628260862,
  "is_trades": 437,
  "is_return_pct": -47.10036610063586,
  "is_mdd_pct": 68.57610261056328,
  "oos_sharpe": 1.2600460956745383,
  "oos_trades": 162,
  "oos_return_pct": 36.107032422417554,
  "oos_mdd_pct": 16.31384727838191,
  "rank_is": 45,
  "selected": false
 },
 {
  "n": 30,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7117806155645761,
  "is_trades": 443,
  "is_return_pct": -44.57461360136866,
  "is_mdd_pct": 68.29971979958451,
  "oos_sharpe": 2.351666316782009,
  "oos_trades": 183,
  "oos_return_pct": 84.98820898856698,
  "oos_mdd_pct": 19.12037972959164,
  "rank_is": 37,
  "selected": false
 },
 {
  "n": 30,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.04529881771744625,
  "is_trades": 458,
  "is_return_pct": -17.319061461728356,
  "is_mdd_pct": 63.770715058331064,
  "oos_sharpe": 2.189102015932647,
  "oos_trades": 178,
  "oos_return_pct": 71.11937222994644,
  "oos_mdd_pct": 18.9314408272124,
  "rank_is": 2,
  "selected": false
 },
 {
  "n": 40,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5316983221186912,
  "is_trades": 435,
  "is_return_pct": -37.33240758533785,
  "is_mdd_pct": 69.04416401663396,
  "oos_sharpe": 1.0256576125593042,
  "oos_trades": 167,
  "oos_return_pct": 26.228463394140668,
  "oos_mdd_pct": 24.455507578087598,
  "rank_is": 21,
  "selected": false
 },
 {
  "n": 40,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.76676875225253,
  "is_trades": 438,
  "is_return_pct": -45.90113593987589,
  "is_mdd_pct": 73.0967840203335,
  "oos_sharpe": 0.7655543356280967,
  "oos_trades": 166,
  "oos_return_pct": 17.88574739601174,
  "oos_mdd_pct": 28.36890261994469,
  "rank_is": 42,
  "selected": false
 },
 {
  "n": 40,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5757116645951728,
  "is_trades": 453,
  "is_return_pct": -40.19363377807591,
  "is_mdd_pct": 68.66885896340797,
  "oos_sharpe": 1.6488147355566503,
  "oos_trades": 162,
  "oos_return_pct": 52.82492986747984,
  "oos_mdd_pct": 12.781500289820558,
  "rank_is": 27,
  "selected": false
 },
 {
  "n": 40,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5540932399879233,
  "is_trades": 455,
  "is_return_pct": -39.464694057277164,
  "is_mdd_pct": 67.45374807562958,
  "oos_sharpe": 2.3618157859115794,
  "oos_trades": 166,
  "oos_return_pct": 89.24520955926334,
  "oos_mdd_pct": 19.58632690016786,
  "rank_is": 25,
  "selected": false
 },
 {
  "n": 40,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.16037247462265455,
  "is_trades": 475,
  "is_return_pct": -23.839779751533918,
  "is_mdd_pct": 61.36485636588853,
  "oos_sharpe": 2.2539143367086907,
  "oos_trades": 180,
  "oos_return_pct": 78.3320705244104,
  "oos_mdd_pct": 18.118706661593663,
  "rank_is": 4,
  "selected": false
 },
 {
  "n": 50,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.19517903115895854,
  "is_trades": 429,
  "is_return_pct": -24.681080325911065,
  "is_mdd_pct": 68.83790081805044,
  "oos_sharpe": 0.9850621978686351,
  "oos_trades": 158,
  "oos_return_pct": 24.667674488485012,
  "oos_mdd_pct": 19.022092106586395,
  "rank_is": 6,
  "selected": false
 },
 {
  "n": 50,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6802683820448674,
  "is_trades": 453,
  "is_return_pct": -45.147704113822684,
  "is_mdd_pct": 72.43716719706872,
  "oos_sharpe": 1.2613415520323026,
  "oos_trades": 163,
  "oos_return_pct": 37.85244714923199,
  "oos_mdd_pct": 18.751872774581603,
  "rank_is": 35,
  "selected": false
 },
 {
  "n": 50,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8562694225193199,
  "is_trades": 451,
  "is_return_pct": -49.728364166142484,
  "is_mdd_pct": 73.3135019417901,
  "oos_sharpe": 1.8693324187592082,
  "oos_trades": 162,
  "oos_return_pct": 63.42897527904867,
  "oos_mdd_pct": 13.577445197282145,
  "rank_is": 47,
  "selected": false
 },
 {
  "n": 50,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.559073115648784,
  "is_trades": 456,
  "is_return_pct": -39.46308670382015,
  "is_mdd_pct": 67.99608251494733,
  "oos_sharpe": 3.1927281902613975,
  "oos_trades": 161,
  "oos_return_pct": 134.93456736647204,
  "oos_mdd_pct": 19.585806851349062,
  "rank_is": 26,
  "selected": false
 },
 {
  "n": 50,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.1831371308231099,
  "is_trades": 472,
  "is_return_pct": -24.971939047730707,
  "is_mdd_pct": 67.33176360946605,
  "oos_sharpe": 2.604188038066268,
  "oos_trades": 179,
  "oos_return_pct": 93.69488926642147,
  "oos_mdd_pct": 17.72995795989425,
  "rank_is": 5,
  "selected": false
 },
 {
  "n": 60,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5109521136075891,
  "is_trades": 441,
  "is_return_pct": -38.726969012856486,
  "is_mdd_pct": 72.91449170816533,
  "oos_sharpe": 1.3826834716782828,
  "oos_trades": 165,
  "oos_return_pct": 40.940518191983344,
  "oos_mdd_pct": 19.28510093225736,
  "rank_is": 19,
  "selected": false
 },
 {
  "n": 60,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5332496706906535,
  "is_trades": 445,
  "is_return_pct": -38.70072973059011,
  "is_mdd_pct": 72.32578185339034,
  "oos_sharpe": 1.2658234140709177,
  "oos_trades": 169,
  "oos_return_pct": 38.32348924366236,
  "oos_mdd_pct": 18.32765256329396,
  "rank_is": 22,
  "selected": false
 },
 {
  "n": 60,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7141841104188618,
  "is_trades": 455,
  "is_return_pct": -45.09865728917642,
  "is_mdd_pct": 70.98198651750435,
  "oos_sharpe": 1.6214699890672473,
  "oos_trades": 173,
  "oos_return_pct": 53.05331074991213,
  "oos_mdd_pct": 16.569409277664484,
  "rank_is": 39,
  "selected": false
 },
 {
  "n": 60,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.2370396602510612,
  "is_trades": 453,
  "is_return_pct": -26.153110489901408,
  "is_mdd_pct": 62.5764417111488,
  "oos_sharpe": 2.5237632949156628,
  "oos_trades": 183,
  "oos_return_pct": 93.93005826781979,
  "oos_mdd_pct": 21.369065081542317,
  "rank_is": 8,
  "selected": false
 },
 {
  "n": 60,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.031039073885631596,
  "is_trades": 462,
  "is_return_pct": -15.933326074833754,
  "is_mdd_pct": 65.77053171615029,
  "oos_sharpe": 2.455260979849456,
  "oos_trades": 175,
  "oos_return_pct": 81.41408316642898,
  "oos_mdd_pct": 27.418492150354425,
  "rank_is": 1,
  "selected": true
 },
 {
  "n": 70,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.0038162041858332,
  "is_trades": 443,
  "is_return_pct": -55.61799662640996,
  "is_mdd_pct": 80.38139620304156,
  "oos_sharpe": 1.9620655599251018,
  "oos_trades": 169,
  "oos_return_pct": 70.88004388667217,
  "oos_mdd_pct": 22.609107755614932,
  "rank_is": 55,
  "selected": false
 },
 {
  "n": 70,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6914926782199534,
  "is_trades": 446,
  "is_return_pct": -44.492718280368805,
  "is_mdd_pct": 75.41692723060083,
  "oos_sharpe": 1.4405921248833091,
  "oos_trades": 173,
  "oos_return_pct": 45.36092399751119,
  "oos_mdd_pct": 22.269242255926468,
  "rank_is": 36,
  "selected": false
 },
 {
  "n": 70,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5518579200310997,
  "is_trades": 443,
  "is_return_pct": -39.344928431843954,
  "is_mdd_pct": 68.70629726721947,
  "oos_sharpe": 1.3007465541132428,
  "oos_trades": 170,
  "oos_return_pct": 37.02421054551597,
  "oos_mdd_pct": 16.665606378869015,
  "rank_is": 24,
  "selected": false
 },
 {
  "n": 70,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5028336889821049,
  "is_trades": 462,
  "is_return_pct": -38.09577970309248,
  "is_mdd_pct": 67.888731050524,
  "oos_sharpe": 2.0556782404495033,
  "oos_trades": 168,
  "oos_return_pct": 73.174574385675,
  "oos_mdd_pct": 26.667549368424513,
  "rank_is": 18,
  "selected": false
 },
 {
  "n": 70,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.3923943159508943,
  "is_trades": 461,
  "is_return_pct": -33.5117419127438,
  "is_mdd_pct": 72.29845706024611,
  "oos_sharpe": 1.9629362191547548,
  "oos_trades": 165,
  "oos_return_pct": 65.4842235252816,
  "oos_mdd_pct": 27.31917910466738,
  "rank_is": 12,
  "selected": false
 },
 {
  "n": 80,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7831863836532996,
  "is_trades": 436,
  "is_return_pct": -48.31626631634599,
  "is_mdd_pct": 75.53743244847483,
  "oos_sharpe": 2.0463964946205797,
  "oos_trades": 169,
  "oos_return_pct": 76.77262118788725,
  "oos_mdd_pct": 22.762037626553187,
  "rank_is": 44,
  "selected": false
 },
 {
  "n": 80,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.9391502965314541,
  "is_trades": 449,
  "is_return_pct": -53.17590203788698,
  "is_mdd_pct": 75.95022253441292,
  "oos_sharpe": 2.030574315362921,
  "oos_trades": 149,
  "oos_return_pct": 77.22314382881461,
  "oos_mdd_pct": 22.40854879029347,
  "rank_is": 54,
  "selected": false
 },
 {
  "n": 80,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7724019304139942,
  "is_trades": 444,
  "is_return_pct": -47.779320882659405,
  "is_mdd_pct": 72.76860353980712,
  "oos_sharpe": 2.2329074496499115,
  "oos_trades": 156,
  "oos_return_pct": 79.81796593456643,
  "oos_mdd_pct": 15.841600203227635,
  "rank_is": 43,
  "selected": false
 },
 {
  "n": 80,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8700976699606091,
  "is_trades": 447,
  "is_return_pct": -50.0912732117748,
  "is_mdd_pct": 71.07810148073624,
  "oos_sharpe": 2.512889465360626,
  "oos_trades": 167,
  "oos_return_pct": 96.4670867036049,
  "oos_mdd_pct": 24.008987254139814,
  "rank_is": 49,
  "selected": false
 },
 {
  "n": 80,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.1723733923846293,
  "is_trades": 472,
  "is_return_pct": -58.65887011060784,
  "is_mdd_pct": 78.40474441744576,
  "oos_sharpe": 2.8567847131215145,
  "oos_trades": 168,
  "oos_return_pct": 119.2714845236,
  "oos_mdd_pct": 19.897998183759714,
  "rank_is": 56,
  "selected": false
 },
 {
  "n": 90,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.7118283887947432,
  "is_trades": 437,
  "is_return_pct": -45.65485998116407,
  "is_mdd_pct": 74.87953307079319,
  "oos_sharpe": 1.174131230588213,
  "oos_trades": 174,
  "oos_return_pct": 32.71194271366957,
  "oos_mdd_pct": 22.812616676600616,
  "rank_is": 38,
  "selected": false
 },
 {
  "n": 90,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8904033848194692,
  "is_trades": 441,
  "is_return_pct": -51.32973143439863,
  "is_mdd_pct": 75.97602611040075,
  "oos_sharpe": 1.4713250070370636,
  "oos_trades": 160,
  "oos_return_pct": 45.688297645770135,
  "oos_mdd_pct": 24.788316040043078,
  "rank_is": 51,
  "selected": false
 },
 {
  "n": 90,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8319848343392804,
  "is_trades": 444,
  "is_return_pct": -49.36357417799715,
  "is_mdd_pct": 73.1666207275719,
  "oos_sharpe": 1.1154591184754488,
  "oos_trades": 163,
  "oos_return_pct": 29.077975070071748,
  "oos_mdd_pct": 16.938820496947017,
  "rank_is": 46,
  "selected": false
 },
 {
  "n": 90,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.213672050528137,
  "is_trades": 449,
  "is_return_pct": -58.871370552143546,
  "is_mdd_pct": 72.02012601893276,
  "oos_sharpe": 2.5923772070867503,
  "oos_trades": 172,
  "oos_return_pct": 103.02471617459989,
  "oos_mdd_pct": 19.158564954974832,
  "rank_is": 57,
  "selected": false
 },
 {
  "n": 90,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.362065185420782,
  "is_trades": 458,
  "is_return_pct": -64.12585714193351,
  "is_mdd_pct": 77.17146398228354,
  "oos_sharpe": 2.945712238171559,
  "oos_trades": 171,
  "oos_return_pct": 121.66542646378286,
  "oos_mdd_pct": 19.669825114569473,
  "rank_is": 60,
  "selected": false
 },
 {
  "n": 100,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.48539839460596346,
  "is_trades": 430,
  "is_return_pct": -38.07172220558673,
  "is_mdd_pct": 73.4449931252965,
  "oos_sharpe": 0.665614515446241,
  "oos_trades": 172,
  "oos_return_pct": 13.595036332543975,
  "oos_mdd_pct": 27.93460012686133,
  "rank_is": 16,
  "selected": false
 },
 {
  "n": 100,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5919513004804996,
  "is_trades": 440,
  "is_return_pct": -42.44093016635551,
  "is_mdd_pct": 76.74535351241222,
  "oos_sharpe": 1.3484188755038895,
  "oos_trades": 161,
  "oos_return_pct": 38.76123967184968,
  "oos_mdd_pct": 23.361370659730383,
  "rank_is": 28,
  "selected": false
 },
 {
  "n": 100,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.3500013141445528,
  "is_trades": 437,
  "is_return_pct": -31.678166811662877,
  "is_mdd_pct": 72.33201585847331,
  "oos_sharpe": 1.7695831620194724,
  "oos_trades": 148,
  "oos_return_pct": 54.93659804380471,
  "oos_mdd_pct": 15.573839231859576,
  "rank_is": 10,
  "selected": false
 },
 {
  "n": 100,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5437249410281639,
  "is_trades": 436,
  "is_return_pct": -38.69027838951442,
  "is_mdd_pct": 68.37655527058233,
  "oos_sharpe": 2.5700515635091534,
  "oos_trades": 161,
  "oos_return_pct": 96.75104373090555,
  "oos_mdd_pct": 19.798461297628034,
  "rank_is": 23,
  "selected": false
 },
 {
  "n": 100,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6458554326971989,
  "is_trades": 449,
  "is_return_pct": -43.18602741646084,
  "is_mdd_pct": 70.23131984942883,
  "oos_sharpe": 3.0620337261392514,
  "oos_trades": 154,
  "oos_return_pct": 122.19495760170345,
  "oos_mdd_pct": 20.982155450095785,
  "rank_is": 31,
  "selected": false
 },
 {
  "n": 110,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -1.2273106570937036,
  "is_trades": 436,
  "is_return_pct": -60.210000897095576,
  "is_mdd_pct": 73.18599956980053,
  "oos_sharpe": 0.38643370740663946,
  "oos_trades": 165,
  "oos_return_pct": 4.76067411554264,
  "oos_mdd_pct": 24.050016637813965,
  "rank_is": 58,
  "selected": false
 },
 {
  "n": 110,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.8800918510060655,
  "is_trades": 439,
  "is_return_pct": -51.437152589206114,
  "is_mdd_pct": 74.09185926667499,
  "oos_sharpe": 0.8835595214004766,
  "oos_trades": 161,
  "oos_return_pct": 20.32197398019693,
  "oos_mdd_pct": 23.175437825182566,
  "rank_is": 50,
  "selected": false
 },
 {
  "n": 110,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.4977836145296808,
  "is_trades": 432,
  "is_return_pct": -36.739432801679804,
  "is_mdd_pct": 66.56354532181213,
  "oos_sharpe": 1.4564889997778538,
  "oos_trades": 156,
  "oos_return_pct": 41.72652444259204,
  "oos_mdd_pct": 16.471803115828276,
  "rank_is": 17,
  "selected": false
 },
 {
  "n": 110,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6560275054278553,
  "is_trades": 441,
  "is_return_pct": -42.92559437398602,
  "is_mdd_pct": 66.91059157700424,
  "oos_sharpe": 3.233093312255079,
  "oos_trades": 158,
  "oos_return_pct": 129.3448712254364,
  "oos_mdd_pct": 15.012243189679786,
  "rank_is": 33,
  "selected": false
 },
 {
  "n": 110,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6522275367231669,
  "is_trades": 446,
  "is_return_pct": -42.78317348784657,
  "is_mdd_pct": 70.51254897083356,
  "oos_sharpe": 3.1922712093402636,
  "oos_trades": 164,
  "oos_return_pct": 129.58811276642535,
  "oos_mdd_pct": 16.197114925694066,
  "rank_is": 32,
  "selected": false
 },
 {
  "n": 120,
  "vol_mult": 1.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.6159835380053816,
  "is_trades": 417,
  "is_return_pct": -41.07093945736173,
  "is_mdd_pct": 63.25417500333161,
  "oos_sharpe": 0.7083724508550013,
  "oos_trades": 169,
  "oos_return_pct": 14.656817799190858,
  "oos_mdd_pct": 21.75423719734827,
  "rank_is": 30,
  "selected": false
 },
 {
  "n": 120,
  "vol_mult": 1.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.5228122568164258,
  "is_trades": 425,
  "is_return_pct": -38.36891929313483,
  "is_mdd_pct": 71.70796688092145,
  "oos_sharpe": 0.9350111154571993,
  "oos_trades": 159,
  "oos_return_pct": 21.997752978375274,
  "oos_mdd_pct": 27.12824804631927,
  "rank_is": 20,
  "selected": false
 },
 {
  "n": 120,
  "vol_mult": 2.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.3776356629569973,
  "is_trades": 426,
  "is_return_pct": -31.556590802438933,
  "is_mdd_pct": 65.37135027170544,
  "oos_sharpe": 1.6457820538109784,
  "oos_trades": 157,
  "oos_return_pct": 48.96617822505305,
  "oos_mdd_pct": 17.709477410671926,
  "rank_is": 11,
  "selected": false
 },
 {
  "n": 120,
  "vol_mult": 2.5,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.09053640876236331,
  "is_trades": 429,
  "is_return_pct": -18.027862398089056,
  "is_mdd_pct": 57.96504380790014,
  "oos_sharpe": 2.012113870069458,
  "oos_trades": 182,
  "oos_return_pct": 63.2643415521837,
  "oos_mdd_pct": 22.244054535672454,
  "rank_is": 3,
  "selected": false
 },
 {
  "n": 120,
  "vol_mult": 3.0,
  "exit_n": 7,
  "status": "ok",
  "is_sharpe": -0.30085652629595644,
  "is_trades": 426,
  "is_return_pct": -27.827687207164576,
  "is_mdd_pct": 66.19216873461944,
  "oos_sharpe": 2.90421896611811,
  "oos_trades": 165,
  "oos_return_pct": 103.67425889117436,
  "oos_mdd_pct": 16.325953276480256,
  "rank_is": 9,
  "selected": false
 }
]

export const realWfSummary: WalkforwardSummary = {
 "objective": "sharpe",
 "min_trades": 20,
 "n_folds": 4,
 "n_validated": 4,
 "positive_folds": 2,
 "wfe": 0.9953142779892133,
 "oos_metrics": {
  "total_return_pct": 1.4335876568175365,
  "cagr_pct": 1.5058040906049452,
  "max_drawdown_pct": 32.41088637290157,
  "mdd_duration_bars": 135,
  "volatility_pct": 46.25852748901668,
  "sharpe": 0.259094900556191,
  "sortino": 0.42032382038924615,
  "calmar": 0.04645982443306251,
  "num_trades": 253,
  "win_rate_pct": 33.201581027667984,
  "profit_factor": 1.05002642965875,
  "avg_win_pct": 13.073750728498407,
  "avg_loss_pct": -5.745515009373298,
  "expectancy_pct": 0.5027787533983361,
  "max_consec_losses": 9
 },
 "params_drift": {
  "n": {
   "values": [
    60,
    120,
    50,
    50
   ],
   "n_distinct": 3,
   "min": 50,
   "max": 120
  },
  "vol_mult": {
   "values": [
    3.0,
    2.5,
    1.0,
    1.0
   ],
   "n_distinct": 3,
   "min": 1.0,
   "max": 3.0
  },
  "exit_n": {
   "values": [
    7,
    7,
    7,
    7
   ],
   "n_distinct": 1,
   "min": 7,
   "max": 7
  }
 },
 "n_combos": 60,
 "holdout": [
  "2026-02-23",
  "2026-08-31"
 ],
 "note": "검증 구간만 이은 곡선(학습 구간은 건너뜀). 조합마다 최적화 구간 전체를 1회 실행해 잘랐다."
}

export const realFolds: FoldsFile = {
 "config": {
  "train_days": 250,
  "test_days": 60,
  "step_days": 60,
  "mode": "rolling"
 },
 "folds": [
  {
   "fold": 0,
   "train": [
    "2024-01-02",
    "2025-01-09"
   ],
   "test": [
    "2025-01-10",
    "2025-04-10"
   ],
   "params": {
    "n": 60,
    "vol_mult": 3.0,
    "exit_n": 7
   },
   "is": {
    "total_return_pct": -41.04771688773414,
    "cagr_pct": -41.29641364927199,
    "max_drawdown_pct": 56.242838519775475,
    "mdd_duration_bars": 141,
    "volatility_pct": 42.470524627593356,
    "sharpe": -1.0459983026382689,
    "sortino": -1.6557214042483266,
    "calmar": -0.7342519463122724,
    "num_trades": 329,
    "win_rate_pct": 30.69908814589666,
    "profit_factor": 0.8114956754780199,
    "avg_win_pct": 10.511174897536305,
    "avg_loss_pct": -5.857468668694896,
    "expectancy_pct": -0.8324443520099364,
    "max_consec_losses": 22
   },
   "oos": {
    "total_return_pct": -13.963191894880623,
    "cagr_pct": -46.829099178707544,
    "max_drawdown_pct": 32.41088637290156,
    "mdd_duration_bars": 31,
    "volatility_pct": 44.52467550785335,
    "sharpe": -1.2000455482416854,
    "sortino": -1.7827523089175537,
    "calmar": -1.4448570964680842,
    "num_trades": 79,
    "win_rate_pct": 30.37974683544304,
    "profit_factor": 0.6968352799569726,
    "avg_win_pct": 10.38245691534886,
    "avg_loss_pct": -5.970638098606098,
    "expectancy_pct": -1.0026092336071235,
    "max_consec_losses": 9
   },
   "is_objective": -1.0459983026382689,
   "oos_objective": -1.2000455482416854
  },
  {
   "fold": 1,
   "train": [
    "2024-03-29",
    "2025-04-10"
   ],
   "test": [
    "2025-04-11",
    "2025-07-10"
   ],
   "params": {
    "n": 120,
    "vol_mult": 2.5,
    "exit_n": 7
   },
   "is": {
    "total_return_pct": -30.25199108267763,
    "cagr_pct": -30.452732882751498,
    "max_drawdown_pct": 57.8449451188767,
    "mdd_duration_bars": 201,
    "volatility_pct": 44.03280056320041,
    "sharpe": -0.6086708239441537,
    "sortino": -0.9635936547151739,
    "calmar": -0.5264545211369519,
    "num_trades": 305,
    "win_rate_pct": 27.54098360655738,
    "profit_factor": 0.8477211887803867,
    "avg_win_pct": 12.690036901815063,
    "avg_loss_pct": -5.99965741852126,
    "expectancy_pct": -0.8523317696417491,
    "max_consec_losses": 15
   },
   "oos": {
    "total_return_pct": 19.664516795134944,
    "cagr_pct": 112.54683589778568,
    "max_drawdown_pct": 17.093602160407695,
    "mdd_duration_bars": 15,
    "volatility_pct": 53.79633962361922,
    "sharpe": 1.6614663599647261,
    "sortino": 3.125913891201337,
    "calmar": 6.584149721143467,
    "num_trades": 58,
    "win_rate_pct": 34.48275862068966,
    "profit_factor": 1.5785999038828584,
    "avg_win_pct": 17.368532719142042,
    "avg_loss_pct": -5.8073684132073335,
    "expectancy_pct": 2.1843216324303825,
    "max_consec_losses": 7
   },
   "is_objective": -0.6086708239441537,
   "oos_objective": 1.6614663599647261
  },
  {
   "fold": 2,
   "train": [
    "2024-06-28",
    "2025-07-10"
   ],
   "test": [
    "2025-07-11",
    "2025-10-10"
   ],
   "params": {
    "n": 50,
    "vol_mult": 1.0,
    "exit_n": 7
   },
   "is": {
    "total_return_pct": 2.776093293610149,
    "cagr_pct": 2.7986099602337555,
    "max_drawdown_pct": 54.25561482275511,
    "mdd_duration_bars": 229,
    "volatility_pct": 48.99449502944109,
    "sharpe": 0.2947463372921043,
    "sortino": 0.5125452609157212,
    "calmar": 0.05158194169168281,
    "num_trades": 277,
    "win_rate_pct": 32.12996389891697,
    "profit_factor": 0.9692690790909665,
    "avg_win_pct": 12.97946017244372,
    "avg_loss_pct": -6.270347480714832,
    "expectancy_pct": -0.08539123114403488,
    "max_consec_losses": 14
   },
   "oos": {
    "total_return_pct": 1.145014285177659,
    "cagr_pct": 4.897905399830815,
    "max_drawdown_pct": 9.339967347567502,
    "mdd_duration_bars": 36,
    "volatility_pct": 24.6339896494827,
    "sharpe": 0.31500068596618014,
    "sortino": 0.46526494757216413,
    "calmar": 0.5244028397065461,
    "num_trades": 46,
    "win_rate_pct": 32.608695652173914,
    "profit_factor": 1.0153106591957346,
    "avg_win_pct": 16.08950220455837,
    "avg_loss_pct": -5.211912891739685,
    "expectancy_pct": 1.7342007266183772,
    "max_consec_losses": 4
   },
   "is_objective": 0.2947463372921043,
   "oos_objective": 0.31500068596618014
  },
  {
   "fold": 3,
   "train": [
    "2024-09-26",
    "2025-10-10"
   ],
   "test": [
    "2025-10-13",
    "2026-01-07"
   ],
   "params": {
    "n": 50,
    "vol_mult": 1.0,
    "exit_n": 7
   },
   "is": {
    "total_return_pct": 74.22656223259894,
    "cagr_pct": 75.0021089199612,
    "max_drawdown_pct": 29.772551345902375,
    "mdd_duration_bars": 104,
    "volatility_pct": 46.61879123402905,
    "sharpe": 1.4282378807110039,
    "sortino": 2.67324513794902,
    "calmar": 2.5191696891735753,
    "num_trades": 256,
    "win_rate_pct": 34.765625,
    "profit_factor": 1.2943526485440215,
    "avg_win_pct": 14.609124871730739,
    "avg_loss_pct": -5.976222784054679,
    "expectancy_pct": 1.180401986901969,
    "max_consec_losses": 11
   },
   "oos": {
    "total_return_pct": -2.593570346861973,
    "cagr_pct": -10.449497986573542,
    "max_drawdown_pct": 19.022092106586395,
    "mdd_duration_bars": 43,
    "volatility_pct": 56.063607279561765,
    "sharpe": 0.0754946201734511,
    "sortino": 0.11931831352447698,
    "calmar": -0.5493348432980937,
    "num_trades": 70,
    "win_rate_pct": 35.714285714285715,
    "profit_factor": 0.9928221369526901,
    "avg_win_pct": 10.412116310971088,
    "avg_loss_pct": -5.785725373665399,
    "expectancy_pct": -0.0007819148666530257,
    "max_consec_losses": 7
   },
   "is_objective": 1.4282378807110039,
   "oos_objective": 0.0754946201734511
  }
 ]
}

export const realHoSummary: HoldoutSummary = {
 "period": [
  "2026-02-23",
  "2026-08-31",
  129
 ],
 "nth_open": 1,
 "nth_open_structure": 1,
 "previous_opens": [],
 "params": {
  "n": 60.0,
  "vol_mult": 3.0,
  "exit_n": 7.0
 },
 "source_run_id": "20260926-001752-4faeb4",
 "structure_hash": "5e11080044c5b1de",
 "family_hash": "19b1ede6c73d3cd2",
 "note": "열람 횟수는 골격 해시 기준. 이 구간은 최적화·선택에 쓰이지 않았다. 사전 판정 기준(criteria)은 이 구간 전체 지표로 판정했다."
}

const base = (d: unknown) => d as RunDetail

export const realOptDetail: RunDetail = base({ ...{
 "run_id": "20260926-001752-4faeb4",
 "meta": {
  "mode": "daily_portfolio",
  "compat": false,
  "spec_hash": "ef4c9fd9d1ad0dc0",
  "structure_hash": "5e11080044c5b1de",
  "params": {
   "n": 60,
   "vol_mult": 3.0,
   "exit_n": 7
  },
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2024-01-02",
   "2026-02-20"
  ],
  "warmup_bars": 600,
  "elapsed_sec": 29.705,
  "warnings": [
   "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
   "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한",
   "이웃 안정성: 최고 목표값이 0 이하라 비율이 뜻이 없다",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
   "데이터 끝에서 강제 청산된 종목 4건(end_of_data)"
  ],
  "kind": "optimize",
  "holdout_used": false,
  "n_combos": 60,
  "workers": 1,
  "run_id": "20260926-001752-4faeb4",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T00:18:24"
 },
 "spec": {
  "version": 1,
  "name": "20일 신고가 돌파 (시연용·미검증)",
  "mode": "daily_portfolio",
  "period": {
   "start": "2024-01-02",
   "end": "2026-08-31"
  },
  "universe": {
   "type": "top_value",
   "n": 60,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": {
         "param": "n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     },
     {
      "left": {
       "kind": "field",
       "name": "volume",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gte",
      "right": {
       "kind": "ind",
       "name": "sma",
       "params": {
        "src": "volume",
        "n": 20
       },
       "offset": 1,
       "mul": {
        "param": "vol_mult"
       }
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "lt",
      "right": {
       "kind": "ind",
       "name": "lowest",
       "params": {
        "src": "low",
        "n": {
         "param": "exit_n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 7.0,
   "take_profit_pct": null,
   "trailing_stop_pct": 10.0,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 5.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 25.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": null,
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {
   "n": {
    "default": 20.0,
    "min": 10.0,
    "max": 120.0,
    "step": 10.0
   },
   "vol_mult": {
    "default": 1.5,
    "min": 1.0,
    "max": 3.0,
    "step": 0.5
   },
   "exit_n": {
    "default": 7.0,
    "min": 3.0,
    "max": 40.0,
    "step": 1.0
   }
  },
  "validation": {
   "holdout_pct": 20.0,
   "objective": "sharpe",
   "min_trades": 20,
   "criteria": {
    "sharpe": 0.5,
    "max_drawdown_pct": 30.0
   }
  }
 },
 "warnings": [
  "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
  "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한",
  "이웃 안정성: 최고 목표값이 0 이하라 비율이 뜻이 없다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
  "데이터 끝에서 강제 청산된 종목 4건(end_of_data)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2024-01",
    "return_pct": -0.8979834379560181
   },
   {
    "period": "2024-02",
    "return_pct": -4.881382758773089
   },
   {
    "period": "2024-03",
    "return_pct": -5.136903842205253
   },
   {
    "period": "2024-04",
    "return_pct": 24.9496295888185
   },
   {
    "period": "2024-05",
    "return_pct": -1.7137790123354368
   },
   {
    "period": "2024-06",
    "return_pct": -5.403352544375172
   },
   {
    "period": "2024-07",
    "return_pct": -14.108892789427818
   },
   {
    "period": "2024-08",
    "return_pct": -18.243725426306955
   },
   {
    "period": "2024-09",
    "return_pct": -21.544404329147504
   },
   {
    "period": "2024-10",
    "return_pct": 9.459146728958956
   },
   {
    "period": "2024-11",
    "return_pct": 2.5839488984045422
   },
   {
    "period": "2024-12",
    "return_pct": -11.845840851822963
   },
   {
    "period": "2025-01",
    "return_pct": 4.259744039692093
   },
   {
    "period": "2025-02",
    "return_pct": 2.5186932398244766
   },
   {
    "period": "2025-03",
    "return_pct": -26.510620441146425
   },
   {
    "period": "2025-04",
    "return_pct": 48.882970132146575
   },
   {
    "period": "2025-05",
    "return_pct": 18.125804918879453
   },
   {
    "period": "2025-06",
    "return_pct": 9.655591308071854
   },
   {
    "period": "2025-07",
    "return_pct": -19.99042150244328
   },
   {
    "period": "2025-08",
    "return_pct": -3.8506048717599772
   },
   {
    "period": "2025-09",
    "return_pct": 19.045059505630757
   },
   {
    "period": "2025-10",
    "return_pct": 23.80776688748214
   },
   {
    "period": "2025-11",
    "return_pct": -2.444140559964414
   },
   {
    "period": "2025-12",
    "return_pct": 24.514543303906542
   },
   {
    "period": "2026-01",
    "return_pct": 24.062695195826333
   },
   {
    "period": "2026-02",
    "return_pct": 4.004314436765877
   }
  ],
  "yearly": [
   {
    "period": "2024",
    "return_pct": -43.34787981478214
   },
   {
    "period": "2025",
    "return_pct": 108.63450131870951
   },
   {
    "period": "2026",
    "return_pct": 29.03055561019365
   }
  ],
  "exit_reasons": [
   {
    "reason": "trailing",
    "n": 381,
    "share_pct": 59.811616954474104,
    "avg_net_pct": 5.397039384363652
   },
   {
    "reason": "stop",
    "n": 238,
    "share_pct": 37.362637362637365,
    "avg_net_pct": -7.417903234484833
   },
   {
    "reason": "signal",
    "n": 14,
    "share_pct": 2.197802197802198,
    "avg_net_pct": -1.1468326559973965
   },
   {
    "reason": "end_of_data",
    "n": 4,
    "share_pct": 0.6279434850863422,
    "avg_net_pct": 6.072294120280719
   }
  ],
  "by_sector": [
   {
    "key": "일반서비스",
    "n": 38,
    "win_rate_pct": 47.368421052631575,
    "net_pnl": 1999451.5479038612,
    "avg_net_pct": 2.8124753220271597
   },
   {
    "key": "운송/창고",
    "n": 10,
    "win_rate_pct": 10.0,
    "net_pnl": 1605554.8850537466,
    "avg_net_pct": 8.933377800185818
   },
   {
    "key": "금융",
    "n": 36,
    "win_rate_pct": 47.22222222222222,
    "net_pnl": 1476273.5591791861,
    "avg_net_pct": 2.4541696080011404
   },
   {
    "key": "화학",
    "n": 39,
    "win_rate_pct": 41.02564102564102,
    "net_pnl": 1432476.5227222906,
    "avg_net_pct": 2.159506313152875
   },
   {
    "key": "오락/문화",
    "n": 9,
    "win_rate_pct": 44.44444444444444,
    "net_pnl": 1156493.236838653,
    "avg_net_pct": 9.417654167598682
   },
   {
    "key": "운송장비/부품",
    "n": 40,
    "win_rate_pct": 40.0,
    "net_pnl": 1028347.7512369715,
    "avg_net_pct": 2.0100731020751184
   },
   {
    "key": "기계/장비",
    "n": 94,
    "win_rate_pct": 30.851063829787233,
    "net_pnl": 995976.1595810697,
    "avg_net_pct": 0.5577083639982455
   },
   {
    "key": "의료/정밀기기",
    "n": 16,
    "win_rate_pct": 37.5,
    "net_pnl": 615469.0512291251,
    "avg_net_pct": 1.3586493006260418
   },
   {
    "key": "증권",
    "n": 5,
    "win_rate_pct": 40.0,
    "net_pnl": 385206.50866949966,
    "avg_net_pct": 2.4011157617707286
   },
   {
    "key": "섬유/의류",
    "n": 7,
    "win_rate_pct": 57.14285714285714,
    "net_pnl": 338830.7829861856,
    "avg_net_pct": 8.963127084814344
   },
   {
    "key": "종이/목재",
    "n": 1,
    "win_rate_pct": 100.0,
    "net_pnl": 31974.78319999975,
    "avg_net_pct": 1.5993789115646133
   },
   {
    "key": "IT 서비스",
    "n": 58,
    "win_rate_pct": 39.6551724137931,
    "net_pnl": -24151.20322422491,
    "avg_net_pct": -0.25833335022679954
   },
   {
    "key": "건설",
    "n": 16,
    "win_rate_pct": 37.5,
    "net_pnl": -128374.41057387672,
    "avg_net_pct": -1.3083405377420585
   },
   {
    "key": "제조",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -148382.14006000006,
    "avg_net_pct": -7.429657116104872
   },
   {
    "key": "기타",
    "n": 7,
    "win_rate_pct": 28.57142857142857,
    "net_pnl": -201741.92045049928,
    "avg_net_pct": -2.5111741307817024
   },
   {
    "key": "비금속",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": -365053.58475001936,
    "avg_net_pct": -3.3907730738947177
   },
   {
    "key": "제약",
    "n": 62,
    "win_rate_pct": 24.193548387096776,
    "net_pnl": -387910.98281889467,
    "avg_net_pct": -0.9597193751177442
   },
   {
    "key": "전기/전자",
    "n": 101,
    "win_rate_pct": 32.67326732673268,
    "net_pnl": -395579.6850620721,
    "avg_net_pct": -0.40223388613003896
   },
   {
    "key": "전기/가스",
    "n": 6,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -427499.21909999993,
    "avg_net_pct": -3.6231670990678135
   },
   {
    "key": "음식료/담배",
    "n": 16,
    "win_rate_pct": 12.5,
    "net_pnl": -1128887.3421494192,
    "avg_net_pct": -5.233073246734585
   },
   {
    "key": "유통",
    "n": 25,
    "win_rate_pct": 20.0,
    "net_pnl": -1152760.1869937945,
    "avg_net_pct": -2.82508237912792
   },
   {
    "key": "금속",
    "n": 42,
    "win_rate_pct": 23.809523809523807,
    "net_pnl": -1454835.5384326058,
    "avg_net_pct": -0.5031302386281536
   }
  ],
  "by_theme_group": [
   {
    "key": "반도체",
    "n": 65,
    "win_rate_pct": 33.84615384615385,
    "net_pnl": 2560460.7095099506,
    "avg_net_pct": 1.7870863785552238
   },
   {
    "key": "지주사",
    "n": 24,
    "win_rate_pct": 58.333333333333336,
    "net_pnl": 1896664.0474838763,
    "avg_net_pct": 4.557025441726005
   },
   {
    "key": "로봇",
    "n": 42,
    "win_rate_pct": 38.095238095238095,
    "net_pnl": 1855598.7486051167,
    "avg_net_pct": 2.3093150229007358
   },
   {
    "key": "바이오",
    "n": 36,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 1650488.5739475791,
    "avg_net_pct": 2.0081746806815337
   },
   {
    "key": "우주",
    "n": 19,
    "win_rate_pct": 52.63157894736842,
    "net_pnl": 1194803.0691753523,
    "avg_net_pct": 4.615189415668562
   },
   {
    "key": "화장품",
    "n": 15,
    "win_rate_pct": 26.666666666666668,
    "net_pnl": 369912.42721172876,
    "avg_net_pct": 1.5791229914932832
   },
   {
    "key": "신재생",
    "n": 16,
    "win_rate_pct": 37.5,
    "net_pnl": 210035.63884817951,
    "avg_net_pct": 0.423748319203124
   },
   {
    "key": "2차전지",
    "n": 27,
    "win_rate_pct": 37.03703703703704,
    "net_pnl": 208588.09564262137,
    "avg_net_pct": 1.7322107877722
   },
   {
    "key": "원전",
    "n": 24,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 179708.80275621242,
    "avg_net_pct": 0.08412588673837504
   },
   {
    "key": "5G",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -57466.860044999536,
    "avg_net_pct": -1.7639351899973572
   },
   {
    "key": "전력",
    "n": 14,
    "win_rate_pct": 35.714285714285715,
    "net_pnl": -155688.08445489977,
    "avg_net_pct": -0.24307396943749868
   },
   {
    "key": "양자",
    "n": 5,
    "win_rate_pct": 40.0,
    "net_pnl": -266440.06092871976,
    "avg_net_pct": -3.9256410268175985
   },
   {
    "key": "조선",
    "n": 25,
    "win_rate_pct": 32.0,
    "net_pnl": -409554.6280906485,
    "avg_net_pct": -0.8451062351132445
   },
   {
    "key": "데이터센터",
    "n": 12,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": -696380.4599395759,
    "avg_net_pct": -2.092489796049156
   },
   {
    "key": "방산",
    "n": 13,
    "win_rate_pct": 23.076923076923077,
    "net_pnl": -783153.1993572344,
    "avg_net_pct": -3.9742859164547077
   },
   {
    "key": "(미분류)",
    "n": 298,
    "win_rate_pct": 30.201342281879196,
    "net_pnl": -2506698.245379358,
    "avg_net_pct": -0.4639327440937654
   }
  ],
  "histogram": {
   "edges": [
    -11.893838753838747,
    -4.159525328000914,
    3.574788097836919,
    11.309101523674752,
    19.043414949512584,
    26.777728375350417,
    34.512041801188246,
    42.246355227026086,
    49.98066865286391,
    57.71498207870174,
    65.44929550453958,
    73.18360893037742,
    80.91792235621524,
    88.65223578205307,
    96.38654920789091,
    104.12086263372875,
    111.85517605956657,
    119.5894894854044,
    127.32380291124223,
    135.0581163370801,
    142.79242976291792
   ],
   "counts": [
    335,
    145,
    74,
    43,
    10,
    10,
    8,
    7,
    1,
    0,
    2,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    0,
    1
   ]
  }
 },
 "narration": "종가가 [n]일 최고가를 넘고 거래량이 1일 전 거래량 20일 이동평균의 [vol_mult]배 이상이면 다음 날 시가에 산다.\n종가가 [exit_n]일 최저가 미만이면 다음 날 시가에 판다.\n청산 규칙: 손절 -7%, 고점 대비 -10% 트레일링.",
 "has_grid": true,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": 52.50878574985174,
  "cagr_pct": 22.743544946379913,
  "max_drawdown_pct": 65.77053171615029,
  "mdd_duration_bars": 368,
  "volatility_pct": 45.63939939364718,
  "sharpe": 0.6724261963642896,
  "sortino": 1.1511080029445577,
  "calmar": 0.34580144561603293,
  "num_trades": 637,
  "win_rate_pct": 33.594976452119305,
  "profit_factor": 1.137043674821734,
  "avg_win_pct": 13.199947705125412,
  "avg_loss_pct": -5.971026605117064,
  "expectancy_pct": 0.469457700050738,
  "max_consec_losses": 22,
  "avg_holding_bars": 3.9419152276295133,
  "exposure_pct": 99.03660886319847,
  "turnover": 114.93914922990517,
  "commission_total": 293061.0584479341,
  "tax_total": 2255771.1154620624,
  "slippage_total": 2669856.492544804,
  "skipped": {
   "slots_full": 2082,
   "cash": 85,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 8
  },
  "benchmark_return_pct": 117.56342211618053,
  "excess_return_pct": -65.0546363663288,
  "beta": 0.5459582771520002
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 2082,
  "cash": 85,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 8
 },
 "n_trades": 637,
 "n_closed": 637,
 "n_codes": 2501,
 "n_bars": 519,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
  "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한",
  "이웃 안정성: 최고 목표값이 0 이하라 비율이 뜻이 없다",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
  "데이터 끝에서 강제 청산된 종목 4건(end_of_data)"
 ],
 "robustness": {
  "n_trades": 637,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": 10469567.241439978,
    "net_return_pct": 104.69567241439978
   },
   {
    "mult": 0.5,
    "net_pnl": 7860222.90821258,
    "net_return_pct": 78.6022290821258
   },
   {
    "mult": 1.0,
    "net_pnl": 5250878.574985182,
    "net_return_pct": 52.50878574985182
   },
   {
    "mult": 1.5,
    "net_pnl": 2641534.241757784,
    "net_return_pct": 26.415342417577843
   },
   {
    "mult": 2.0,
    "net_pnl": 32189.908530386165,
    "net_return_pct": 0.32189908530386163
   },
   {
    "mult": 3.0,
    "net_pnl": -5186498.75792441,
    "net_return_pct": -51.864987579244094
   }
  ],
  "breakeven_cost_mult": 2.006168198677438,
  "cost_sensitivity_meta": {
   "gross_before_costs": 10469567.241439978,
   "total_costs": 5218688.666454796,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 637,
   "weight": 0.15274259646028257,
   "final_return_pct": {
    "p5": -38.96637949114208,
    "p50": 36.92891552569701,
    "p95": 217.4075603663733
   },
   "max_drawdown_pct": {
    "p5": 19.920811496380136,
    "p50": 33.70319892358896,
    "p95": 55.84956141275717
   },
   "prob_mdd_gt_30": 0.639,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": 5250878.574985183,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "084670"
     ],
     "removed_pnl": 2607318.371256,
     "net_pnl_excluding": 2643560.203729183,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "084670",
      "389140"
     ],
     "removed_pnl": 3921120.7109785,
     "net_pnl_excluding": 1329757.8640066828,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "084670",
      "389140",
      "323280"
     ],
     "removed_pnl": 5020823.94158067,
     "net_pnl_excluding": 230054.6334045129,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2025-12-19"
     ],
     "removed_pnl": 2496108.168971,
     "net_pnl_excluding": 2754770.406014183,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2025-12-19",
      "2026-02-20"
     ],
     "removed_pnl": 3966322.4343360006,
     "net_pnl_excluding": 1284556.1406491823,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2025-12-19",
      "2026-02-20",
      "2024-04-08"
     ],
     "removed_pnl": 5313876.682313821,
     "net_pnl_excluding": -62998.107328638434,
     "sign_flipped": true
    }
   ]
  }
 },
 "criteria": [
  {
   "metric": "sharpe",
   "threshold": 0.5,
   "direction": "min",
   "value": 0.6724261963642896,
   "passed": true,
   "note": null
  },
  {
   "metric": "max_drawdown_pct",
   "threshold": 30.0,
   "direction": "max",
   "value": 65.77053171615029,
   "passed": false,
   "note": null
  }
 ]
}, optimize: realOptSummary } })
export const realWfDetail: RunDetail = base({ ...{
 "run_id": "20260926-001825-48187c",
 "meta": {
  "kind": "walkforward",
  "mode": "daily_portfolio",
  "warnings": [
   "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
   "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한"
  ],
  "holdout_used": false,
  "n_combos": 60,
  "workers": 1,
  "spec_hash": null,
  "structure_hash": "5e11080044c5b1de",
  "elapsed_sec": 25.697,
  "run_id": "20260926-001825-48187c",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T00:18:52"
 },
 "spec": {
  "version": 1,
  "name": "20일 신고가 돌파 (시연용·미검증)",
  "mode": "daily_portfolio",
  "period": {
   "start": "2024-01-02",
   "end": "2026-08-31"
  },
  "universe": {
   "type": "top_value",
   "n": 60,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": {
         "param": "n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     },
     {
      "left": {
       "kind": "field",
       "name": "volume",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gte",
      "right": {
       "kind": "ind",
       "name": "sma",
       "params": {
        "src": "volume",
        "n": 20
       },
       "offset": 1,
       "mul": {
        "param": "vol_mult"
       }
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "lt",
      "right": {
       "kind": "ind",
       "name": "lowest",
       "params": {
        "src": "low",
        "n": {
         "param": "exit_n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 7.0,
   "take_profit_pct": null,
   "trailing_stop_pct": 10.0,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 5.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 25.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": null,
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {
   "n": {
    "default": 20.0,
    "min": 10.0,
    "max": 120.0,
    "step": 10.0
   },
   "vol_mult": {
    "default": 1.5,
    "min": 1.0,
    "max": 3.0,
    "step": 0.5
   },
   "exit_n": {
    "default": 7.0,
    "min": 3.0,
    "max": 40.0,
    "step": 1.0
   }
  },
  "validation": {
   "holdout_pct": 20.0,
   "objective": "sharpe",
   "min_trades": 20,
   "criteria": {
    "sharpe": 0.5,
    "max_drawdown_pct": 30.0
   }
  }
 },
 "warnings": [
  "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
  "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2025-01",
    "return_pct": 0.1918032346358567
   },
   {
    "period": "2025-02",
    "return_pct": 2.5186932398244988
   },
   {
    "period": "2025-03",
    "return_pct": -26.510620441146425
   },
   {
    "period": "2025-04",
    "return_pct": 15.958140931190723
   },
   {
    "period": "2025-05",
    "return_pct": 22.72239813051218
   },
   {
    "period": "2025-06",
    "return_pct": 9.774730140784849
   },
   {
    "period": "2025-07",
    "return_pct": -13.479811268654062
   },
   {
    "period": "2025-08",
    "return_pct": -3.519759402316658
   },
   {
    "period": "2025-09",
    "return_pct": 2.606593406294766
   },
   {
    "period": "2025-10",
    "return_pct": 5.401656260055243
   },
   {
    "period": "2025-11",
    "return_pct": -7.903111369244742
   },
   {
    "period": "2025-12",
    "return_pct": -2.0188582288838575
   },
   {
    "period": "2026-01",
    "return_pct": 5.591388494952443
   }
  ],
  "yearly": [
   {
    "period": "2025",
    "return_pct": -3.9376325071562635
   },
   {
    "period": "2026",
    "return_pct": 5.591388494952443
   }
  ],
  "exit_reasons": [
   {
    "reason": "trailing",
    "n": 152,
    "share_pct": 60.079051383399204,
    "avg_net_pct": 5.474714784515981
   },
   {
    "reason": "stop",
    "n": 93,
    "share_pct": 36.75889328063241,
    "avg_net_pct": -7.431254517229978
   },
   {
    "reason": "signal",
    "n": 8,
    "share_pct": 3.1620553359683794,
    "avg_net_pct": -1.7308690667827926
   }
  ],
  "by_sector": [
   {
    "key": "금융",
    "n": 19,
    "win_rate_pct": 42.10526315789473,
    "net_pnl": 988582.051860085,
    "avg_net_pct": 4.284537774392302
   },
   {
    "key": "화학",
    "n": 14,
    "win_rate_pct": 50.0,
    "net_pnl": 833236.9972157998,
    "avg_net_pct": 8.37618069540422
   },
   {
    "key": "일반서비스",
    "n": 20,
    "win_rate_pct": 35.0,
    "net_pnl": 689525.6096693667,
    "avg_net_pct": 1.62817118888632
   },
   {
    "key": "기계/장비",
    "n": 31,
    "win_rate_pct": 38.70967741935484,
    "net_pnl": 621612.8121418159,
    "avg_net_pct": 1.938755361402781
   },
   {
    "key": "의료/정밀기기",
    "n": 3,
    "win_rate_pct": 66.66666666666666,
    "net_pnl": 491979.1828488852,
    "avg_net_pct": 9.930482362380692
   },
   {
    "key": "섬유/의류",
    "n": 3,
    "win_rate_pct": 66.66666666666666,
    "net_pnl": 318421.8520232753,
    "avg_net_pct": 12.865059510221286
   },
   {
    "key": "제약",
    "n": 19,
    "win_rate_pct": 36.84210526315789,
    "net_pnl": 100755.27825038355,
    "avg_net_pct": 0.010050101674552083
   },
   {
    "key": "건설",
    "n": 12,
    "win_rate_pct": 50.0,
    "net_pnl": 35651.61827072271,
    "avg_net_pct": 2.251610720360231
   },
   {
    "key": "IT 서비스",
    "n": 18,
    "win_rate_pct": 38.88888888888889,
    "net_pnl": -53872.49054690731,
    "avg_net_pct": -0.1427759826184624
   },
   {
    "key": "운송/창고",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -58208.126706749885,
    "avg_net_pct": -3.816262585059834
   },
   {
    "key": "증권",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -95535.62552413538,
    "avg_net_pct": -7.335622150000008
   },
   {
    "key": "비금속",
    "n": 2,
    "win_rate_pct": 50.0,
    "net_pnl": -103435.28360707642,
    "avg_net_pct": -2.6421129042682914
   },
   {
    "key": "오락/문화",
    "n": 5,
    "win_rate_pct": 20.0,
    "net_pnl": -150805.60440399998,
    "avg_net_pct": -3.099761013781204
   },
   {
    "key": "전기/전자",
    "n": 33,
    "win_rate_pct": 30.303030303030305,
    "net_pnl": -189030.1080210362,
    "avg_net_pct": -0.8299686441892233
   },
   {
    "key": "유통",
    "n": 11,
    "win_rate_pct": 27.27272727272727,
    "net_pnl": -292200.86523699464,
    "avg_net_pct": -3.101007628423411
   },
   {
    "key": "기타",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -334509.76442899986,
    "avg_net_pct": -7.425216123995397
   },
   {
    "key": "전기/가스",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": -346199.05325,
    "avg_net_pct": -5.244267099111997
   },
   {
    "key": "음식료/담배",
    "n": 8,
    "win_rate_pct": 12.5,
    "net_pnl": -368505.8645461689,
    "avg_net_pct": -3.8655973111794237
   },
   {
    "key": "운송장비/부품",
    "n": 26,
    "win_rate_pct": 26.923076923076923,
    "net_pnl": -662141.3072049762,
    "avg_net_pct": -0.5738519718187488
   },
   {
    "key": "금속",
    "n": 18,
    "win_rate_pct": 11.11111111111111,
    "net_pnl": -779196.7608142477,
    "avg_net_pct": -3.722020269371011
   }
  ],
  "by_theme_group": [
   {
    "key": "바이오",
    "n": 16,
    "win_rate_pct": 43.75,
    "net_pnl": 832602.3953921573,
    "avg_net_pct": 2.8942205456598593
   },
   {
    "key": "조선",
    "n": 15,
    "win_rate_pct": 46.666666666666664,
    "net_pnl": 473012.545261251,
    "avg_net_pct": 4.227149801024603
   },
   {
    "key": "화장품",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": 452643.3572439995,
    "avg_net_pct": 5.662571758023898
   },
   {
    "key": "우주",
    "n": 9,
    "win_rate_pct": 44.44444444444444,
    "net_pnl": 226214.84053256823,
    "avg_net_pct": 3.465222846824525
   },
   {
    "key": "지주사",
    "n": 12,
    "win_rate_pct": 41.66666666666667,
    "net_pnl": 181893.63452355092,
    "avg_net_pct": 5.986836225192215
   },
   {
    "key": "전력",
    "n": 4,
    "win_rate_pct": 50.0,
    "net_pnl": 179601.41181360034,
    "avg_net_pct": 5.012629324113779
   },
   {
    "key": "원전",
    "n": 14,
    "win_rate_pct": 35.714285714285715,
    "net_pnl": 160083.99959160003,
    "avg_net_pct": 0.5696675503433587
   },
   {
    "key": "로봇",
    "n": 24,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 61428.10747795232,
    "avg_net_pct": 0.7895912752954081
   },
   {
    "key": "5G",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -36305.1294,
    "avg_net_pct": -2.460163811563169
   },
   {
    "key": "신재생",
    "n": 6,
    "win_rate_pct": 16.666666666666664,
    "net_pnl": -54504.61586002707,
    "avg_net_pct": -0.5160771720936277
   },
   {
    "key": "데이터센터",
    "n": 4,
    "win_rate_pct": 50.0,
    "net_pnl": -88814.26350049968,
    "avg_net_pct": -0.7437985306009506
   },
   {
    "key": "반도체",
    "n": 17,
    "win_rate_pct": 23.52941176470588,
    "net_pnl": -200967.87929946417,
    "avg_net_pct": -1.400070508467049
   },
   {
    "key": "2차전지",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": -365200.5152349997,
    "avg_net_pct": -2.8467519303454267
   },
   {
    "key": "방산",
    "n": 4,
    "win_rate_pct": 0.0,
    "net_pnl": -373827.1144050004,
    "avg_net_pct": -7.095360695963677
   },
   {
    "key": "(미분류)",
    "n": 115,
    "win_rate_pct": 31.30434782608696,
    "net_pnl": -801736.2261476467,
    "avg_net_pct": -0.6232926457672682
   }
  ],
  "histogram": {
   "edges": [
    -9.438845486111113,
    -6.256235443948415,
    -3.0736254017857174,
    0.10898464037698119,
    3.291594682539678,
    6.474204724702375,
    9.656814766865075,
    12.839424809027772,
    16.02203485119047,
    19.204644893353166,
    22.387254935515863,
    25.569864977678563,
    28.752475019841263,
    31.935085062003957,
    35.11769510416666,
    38.30030514632935,
    41.48291518849205,
    44.66552523065475,
    47.848135272817444,
    51.030745314980145,
    54.213355357142845
   ],
   "counts": [
    99,
    41,
    30,
    22,
    12,
    8,
    7,
    9,
    7,
    1,
    3,
    3,
    2,
    1,
    3,
    2,
    1,
    0,
    1,
    1
   ]
  }
 },
 "narration": "종가가 [n]일 최고가를 넘고 거래량이 1일 전 거래량 20일 이동평균의 [vol_mult]배 이상이면 다음 날 시가에 산다.\n종가가 [exit_n]일 최저가 미만이면 다음 날 시가에 판다.\n청산 규칙: 손절 -7%, 고점 대비 -10% 트레일링.",
 "has_grid": true,
 "has_folds": true
}, summary: { ...{
 "metrics": {
  "total_return_pct": 1.4335876568175365,
  "cagr_pct": 1.5058040906049452,
  "max_drawdown_pct": 32.41088637290157,
  "mdd_duration_bars": 135,
  "volatility_pct": 46.25852748901668,
  "sharpe": 0.259094900556191,
  "sortino": 0.42032382038924615,
  "calmar": 0.04645982443306251,
  "num_trades": 253,
  "win_rate_pct": 33.201581027667984,
  "profit_factor": 1.05002642965875,
  "avg_win_pct": 13.073750728498407,
  "avg_loss_pct": -5.745515009373298,
  "expectancy_pct": 0.5027787533983361,
  "max_consec_losses": 9
 },
 "n_trades": 253,
 "n_closed": 253,
 "warnings": [
  "홀드아웃 2026-02-23~2026-08-31(129거래일)는 최적화·선택·OOS 어디에도 쓰지 않았다 — holdout_check 로만 연다",
  "메모리 부족으로 직렬 실행(요청 워커 8개, 워커당 추정 1.7GB) — 다른 프로그램을 위한 예비 메모리를 남기려는 상한"
 ],
 "criteria": [
  {
   "metric": "sharpe",
   "threshold": 0.5,
   "direction": "min",
   "value": 0.259094900556191,
   "passed": false,
   "note": null
  },
  {
   "metric": "max_drawdown_pct",
   "threshold": 30.0,
   "direction": "max",
   "value": 32.41088637290157,
   "passed": false,
   "note": null
  }
 ]
}, walkforward: realWfSummary } })
export const realHoDetail: RunDetail = base({ ...{
 "run_id": "20260926-001853-680718",
 "meta": {
  "mode": "daily_portfolio",
  "compat": false,
  "spec_hash": "8f34bcd0e33f2270",
  "structure_hash": "5e11080044c5b1de",
  "params": {
   "n": 60.0,
   "vol_mult": 3.0,
   "exit_n": 7.0
  },
  "data": {
   "daily": [
    "2019-04-23",
    "2026-09-23"
   ],
   "kospi": [
    "2021-07-26",
    "2026-09-23"
   ],
   "kosdaq": [
    "2021-07-26",
    "2026-09-23"
   ],
   "minute_al": [
    "2025-08-01",
    "2026-09-23"
   ],
   "tick_al": [
    "2026-08-04",
    "2026-09-23"
   ]
  },
  "period_used": [
   "2026-02-23",
   "2026-08-31"
  ],
  "warmup_bars": 600,
  "elapsed_sec": 6.717,
  "warnings": [
   "일봉이 기간 끝보다 먼저 끝난 종목 7개(상장폐지·수집 중단) — 마지막 종가로 청산됨",
   "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
   "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
   "데이터 끝에서 강제 청산된 종목 1건(end_of_data)"
  ],
  "kind": "holdout_check",
  "holdout_open_count": 1,
  "family_hash": "19b1ede6c73d3cd2",
  "run_id": "20260926-001853-680718",
  "engine_version": "0.1.0",
  "git": {
   "commit": "2392556",
   "dirty": true
  },
  "created_at": "2026-09-26T00:19:01"
 },
 "spec": {
  "version": 1,
  "name": "20일 신고가 돌파 (시연용·미검증)",
  "mode": "daily_portfolio",
  "period": {
   "start": "2024-01-02",
   "end": "2026-08-31"
  },
  "universe": {
   "type": "top_value",
   "n": 60,
   "lookback_days": 1,
   "markets": [
    "거래소",
    "코스닥"
   ],
   "exclude": [
    "spac",
    "preferred",
    "mega_cap"
   ],
   "codes": []
  },
  "strategy": {
   "source": "builder",
   "entry": {
    "logic": "all",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gt",
      "right": {
       "kind": "ind",
       "name": "highest",
       "params": {
        "src": "high",
        "n": {
         "param": "n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     },
     {
      "left": {
       "kind": "field",
       "name": "volume",
       "offset": 0,
       "mul": 1.0
      },
      "op": "gte",
      "right": {
       "kind": "ind",
       "name": "sma",
       "params": {
        "src": "volume",
        "n": 20
       },
       "offset": 1,
       "mul": {
        "param": "vol_mult"
       }
      }
     }
    ]
   },
   "exit": {
    "logic": "any",
    "items": [
     {
      "left": {
       "kind": "field",
       "name": "close",
       "offset": 0,
       "mul": 1.0
      },
      "op": "lt",
      "right": {
       "kind": "ind",
       "name": "lowest",
       "params": {
        "src": "low",
        "n": {
         "param": "exit_n"
        }
       },
       "offset": 0,
       "mul": 1.0
      }
     }
    ]
   }
  },
  "market_filter": null,
  "exits": {
   "stop_loss_pct": 7.0,
   "take_profit_pct": null,
   "trailing_stop_pct": 10.0,
   "max_holding_bars": null
  },
  "portfolio": {
   "initial_capital": 10000000.0,
   "max_positions": 5.0,
   "sizing": "equal_slot_fixed",
   "fixed_amount": null,
   "risk_pct": null,
   "max_weight_pct": 25.0,
   "rank_by": "value",
   "random_seed": 42
  },
  "costs": {
   "commission_rate": 0.00015,
   "tax_rate": 0.0023,
   "slippage_mode": "max_rate_tick",
   "slippage_rate": 0.001,
   "slippage_ticks": 1
  },
  "fills": {
   "same_bar_policy": "stop_first",
   "volume_cap_pct": 10.0
  },
  "intraday": null,
  "tick": null,
  "compat": {
   "legacy": false
  },
  "params": {
   "n": {
    "default": 20.0,
    "min": 10.0,
    "max": 120.0,
    "step": 10.0
   },
   "vol_mult": {
    "default": 1.5,
    "min": 1.0,
    "max": 3.0,
    "step": 0.5
   },
   "exit_n": {
    "default": 7.0,
    "min": 3.0,
    "max": 40.0,
    "step": 1.0
   }
  },
  "validation": {
   "holdout_pct": 20.0,
   "objective": "sharpe",
   "min_trades": 20,
   "criteria": {
    "sharpe": 0.5,
    "max_drawdown_pct": 30.0
   }
  }
 },
 "warnings": [
  "일봉이 기간 끝보다 먼저 끝난 종목 7개(상장폐지·수집 중단) — 마지막 종가로 청산됨",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
  "데이터 끝에서 강제 청산된 종목 1건(end_of_data)"
 ],
 "analysis": {
  "monthly": [
   {
    "period": "2026-02",
    "return_pct": -4.166046237361232
   },
   {
    "period": "2026-03",
    "return_pct": -22.74512216106427
   },
   {
    "period": "2026-04",
    "return_pct": 8.904345089113974
   },
   {
    "period": "2026-05",
    "return_pct": 3.87789005414938
   },
   {
    "period": "2026-06",
    "return_pct": -26.013743668887145
   },
   {
    "period": "2026-07",
    "return_pct": 8.75017766852797
   },
   {
    "period": "2026-08",
    "return_pct": 6.860937658623412
   }
  ],
  "yearly": [
   {
    "period": "2026",
    "return_pct": -27.986544269925172
   }
  ],
  "exit_reasons": [
   {
    "reason": "stop",
    "n": 106,
    "share_pct": 55.78947368421052,
    "avg_net_pct": -7.401501748460891
   },
   {
    "reason": "trailing",
    "n": 83,
    "share_pct": 43.684210526315795,
    "avg_net_pct": 7.877388087995345
   },
   {
    "reason": "end_of_data",
    "n": 1,
    "share_pct": 0.5263157894736842,
    "avg_net_pct": 12.018814481280689
   }
  ],
  "by_sector": [
   {
    "key": "전기/전자",
    "n": 43,
    "win_rate_pct": 32.55813953488372,
    "net_pnl": 2222232.595910823,
    "avg_net_pct": 5.1631087152191775
   },
   {
    "key": "음식료/담배",
    "n": 4,
    "win_rate_pct": 50.0,
    "net_pnl": 679746.1237124,
    "avg_net_pct": 10.003764469668885
   },
   {
    "key": "건설",
    "n": 10,
    "win_rate_pct": 20.0,
    "net_pnl": 230899.59756635485,
    "avg_net_pct": 0.5675928969556071
   },
   {
    "key": "유통",
    "n": 11,
    "win_rate_pct": 18.181818181818183,
    "net_pnl": 155675.6831354996,
    "avg_net_pct": 0.48015283810256043
   },
   {
    "key": "운송/창고",
    "n": 4,
    "win_rate_pct": 25.0,
    "net_pnl": 145064.8216999997,
    "avg_net_pct": 0.89281330405648
   },
   {
    "key": "제약",
    "n": 6,
    "win_rate_pct": 33.33333333333333,
    "net_pnl": 113331.13201472792,
    "avg_net_pct": 1.2641315303151586
   },
   {
    "key": "보험",
    "n": 2,
    "win_rate_pct": 100.0,
    "net_pnl": 51736.93199999977,
    "avg_net_pct": 1.5008031567775273
   },
   {
    "key": "종이/목재",
    "n": 1,
    "win_rate_pct": 100.0,
    "net_pnl": 50051.396,
    "avg_net_pct": 2.616560247167868
   },
   {
    "key": "의료/정밀기기",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -8981.85775,
    "avg_net_pct": -0.46830510440835266
   },
   {
    "key": "오락/문화",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -22770.53875,
    "avg_net_pct": -7.40505325203252
   },
   {
    "key": "금융",
    "n": 8,
    "win_rate_pct": 37.5,
    "net_pnl": -24270.4812384384,
    "avg_net_pct": -1.1930263742747143
   },
   {
    "key": "기타",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -126300.15895199985,
    "avg_net_pct": -3.6299415611912424
   },
   {
    "key": "통신",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -139809.91598173592,
    "avg_net_pct": -7.335622149999997
   },
   {
    "key": "비금속",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -161017.98697500027,
    "avg_net_pct": -7.421751449163779
   },
   {
    "key": "증권",
    "n": 3,
    "win_rate_pct": 0.0,
    "net_pnl": -407512.03319500026,
    "avg_net_pct": -7.353850139190399
   },
   {
    "key": "일반서비스",
    "n": 8,
    "win_rate_pct": 12.5,
    "net_pnl": -582267.1459705005,
    "avg_net_pct": -5.30729610562651
   },
   {
    "key": "금속",
    "n": 18,
    "win_rate_pct": 22.22222222222222,
    "net_pnl": -804284.11446347,
    "avg_net_pct": -3.412166493090852
   },
   {
    "key": "화학",
    "n": 22,
    "win_rate_pct": 27.27272727272727,
    "net_pnl": -893365.9266084682,
    "avg_net_pct": -2.4320232135139888
   },
   {
    "key": "IT 서비스",
    "n": 12,
    "win_rate_pct": 8.333333333333332,
    "net_pnl": -955608.03153219,
    "avg_net_pct": -4.547251959458945
   },
   {
    "key": "기계/장비",
    "n": 21,
    "win_rate_pct": 19.047619047619047,
    "net_pnl": -1123050.026427879,
    "avg_net_pct": -2.8219148495282793
   },
   {
    "key": "운송장비/부품",
    "n": 10,
    "win_rate_pct": 0.0,
    "net_pnl": -1198154.4911876395,
    "avg_net_pct": -6.835047162210826
   }
  ],
  "by_theme_group": [
   {
    "key": "전력",
    "n": 7,
    "win_rate_pct": 71.42857142857143,
    "net_pnl": 3515527.8831134997,
    "avg_net_pct": 32.068591978000214
   },
   {
    "key": "바이오",
    "n": 4,
    "win_rate_pct": 50.0,
    "net_pnl": 305000.26257115405,
    "avg_net_pct": 4.716691578773411
   },
   {
    "key": "방산",
    "n": 11,
    "win_rate_pct": 18.181818181818183,
    "net_pnl": 190144.0871584726,
    "avg_net_pct": 0.2903871910015245
   },
   {
    "key": "데이터센터",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": 111670.23277595785,
    "avg_net_pct": 0.5727978330977136
   },
   {
    "key": "조선",
    "n": 2,
    "win_rate_pct": 0.0,
    "net_pnl": -131651.17517500016,
    "avg_net_pct": -7.404422348384967
   },
   {
    "key": "5G",
    "n": 1,
    "win_rate_pct": 0.0,
    "net_pnl": -143637.9195,
    "avg_net_pct": -7.339699514563107
   },
   {
    "key": "양자",
    "n": 4,
    "win_rate_pct": 0.0,
    "net_pnl": -307758.31477162114,
    "avg_net_pct": -5.8707786913516955
   },
   {
    "key": "화장품",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": -315572.9702937323,
    "avg_net_pct": -3.025744166179044
   },
   {
    "key": "지주사",
    "n": 5,
    "win_rate_pct": 20.0,
    "net_pnl": -405323.4993084383,
    "avg_net_pct": -3.9613273451322097
   },
   {
    "key": "2차전지",
    "n": 8,
    "win_rate_pct": 25.0,
    "net_pnl": -484885.1835544305,
    "avg_net_pct": -4.372774959220574
   },
   {
    "key": "원전",
    "n": 4,
    "win_rate_pct": 0.0,
    "net_pnl": -517381.961000488,
    "avg_net_pct": -7.077736880649111
   },
   {
    "key": "로봇",
    "n": 9,
    "win_rate_pct": 11.11111111111111,
    "net_pnl": -689255.9591686145,
    "avg_net_pct": -4.752868223306626
   },
   {
    "key": "반도체",
    "n": 30,
    "win_rate_pct": 30.0,
    "net_pnl": -908735.5254689645,
    "avg_net_pct": -1.9102063031283534
   },
   {
    "key": "우주",
    "n": 12,
    "win_rate_pct": 8.333333333333332,
    "net_pnl": -917610.2043067853,
    "avg_net_pct": -3.8652545310418485
   },
   {
    "key": "(미분류)",
    "n": 67,
    "win_rate_pct": 26.865671641791046,
    "net_pnl": -978205.9486055273,
    "avg_net_pct": -0.012981550259546002
   },
   {
    "key": "신재생",
    "n": 10,
    "win_rate_pct": 0.0,
    "net_pnl": -1120978.231458,
    "avg_net_pct": -6.956849390715757
   }
  ],
  "histogram": {
   "edges": [
    -11.457113233587211,
    -4.756026360722033,
    1.9450605121431455,
    8.646147385008323,
    15.347234257873502,
    22.04832113073868,
    28.749408003603858,
    35.45049487646904,
    42.15158174933421,
    48.85266862219939,
    55.55375549506458,
    62.254842367929754,
    68.95592924079493,
    75.6570161136601,
    82.3581029865253,
    89.05918985939047,
    95.76027673225565,
    102.46136360512082,
    109.162450477986,
    115.86353735085119,
    122.56462422371635
   ],
   "counts": [
    123,
    30,
    10,
    10,
    5,
    5,
    0,
    3,
    0,
    1,
    1,
    0,
    0,
    1,
    0,
    0,
    0,
    0,
    0,
    1
   ]
  }
 },
 "narration": "종가가 [n]일 최고가를 넘고 거래량이 1일 전 거래량 20일 이동평균의 [vol_mult]배 이상이면 다음 날 시가에 산다.\n종가가 [exit_n]일 최저가 미만이면 다음 날 시가에 판다.\n청산 규칙: 손절 -7%, 고점 대비 -10% 트레일링.",
 "has_grid": false,
 "has_folds": false
}, summary: { ...{
 "metrics": {
  "total_return_pct": -27.986544269925172,
  "cagr_pct": -47.34262236357812,
  "max_drawdown_pct": 38.22630738168641,
  "mdd_duration_bars": 127,
  "volatility_pct": 57.81904636828856,
  "sharpe": -0.8243005627849868,
  "sortino": -1.2322263099299455,
  "calmar": -1.2384827519662334,
  "num_trades": 190,
  "win_rate_pct": 23.684210526315788,
  "profit_factor": 0.8122077092938992,
  "avg_win_pct": 18.43646966011634,
  "avg_loss_pct": -6.540402029359971,
  "expectancy_pct": -0.624827155536633,
  "max_consec_losses": 20,
  "avg_holding_bars": 2.0631578947368423,
  "exposure_pct": 68.21705426356588,
  "turnover": 40.29686472842204,
  "commission_total": 90174.8586167672,
  "tax_total": 689018.2021573981,
  "slippage_total": 825614.0315683408,
  "skipped": {
   "slots_full": 147,
   "cash": 20,
   "upper_limit": 0,
   "volume_cap": 0,
   "no_data": 4
  },
  "benchmark_return_pct": 16.659510886763627,
  "excess_return_pct": -44.6460551566888,
  "beta": 0.24689499118304287
 },
 "legacy_metrics": null,
 "skipped": {
  "slots_full": 147,
  "cash": 20,
  "upper_limit": 0,
  "volume_cap": 0,
  "no_data": 4
 },
 "n_trades": 190,
 "n_closed": 190,
 "n_codes": 2501,
 "n_bars": 129,
 "universe_excluded": {
  "spac": 64,
  "preferred": 7,
  "mega_cap": 2,
  "market_unknown": 0,
  "market_other": 0
 },
 "warnings": [
  "일봉이 기간 끝보다 먼저 끝난 종목 7개(상장폐지·수집 중단) — 마지막 종가로 청산됨",
  "생존 편향: 일봉 캐시는 현재 살아있는 종목 기준이라 상장폐지·거래정지 종목이 표본에서 빠져 있다",
  "거래대금은 KRX 일봉 종가×거래량 근사값이다(통합 AL 실거래대금이 아님)",
  "데이터 끝에서 강제 청산된 종목 1건(end_of_data)"
 ],
 "robustness": {
  "n_trades": 190,
  "cost_sensitivity": [
   {
    "mult": 0.0,
    "net_pnl": -1193847.3346500124,
    "net_return_pct": -11.938473346500125
   },
   {
    "mult": 0.5,
    "net_pnl": -1996250.8808212655,
    "net_return_pct": -19.962508808212657
   },
   {
    "mult": 1.0,
    "net_pnl": -2798654.426992519,
    "net_return_pct": -27.98654426992519
   },
   {
    "mult": 1.5,
    "net_pnl": -3601057.9731637714,
    "net_return_pct": -36.01057973163771
   },
   {
    "mult": 2.0,
    "net_pnl": -4403461.519335025,
    "net_return_pct": -44.03461519335025
   },
   {
    "mult": 3.0,
    "net_pnl": -6008268.611677531,
    "net_return_pct": -60.08268611677531
   }
  ],
  "breakeven_cost_mult": 0.0,
  "cost_sensitivity_meta": {
   "gross_before_costs": -1193847.3346500124,
   "total_costs": 1604807.0923425062,
   "approximation": "같은 거래·같은 수량을 가정한 사후 계산(비용이 바뀌면 달라질 사이징·건너뜀은 미반영)"
  },
  "monte_carlo": {
   "n_sims": 1000,
   "seed": 42,
   "n_trades": 190,
   "weight": 0.1587329435468421,
   "final_return_pct": {
    "p5": -53.28504621082964,
    "p50": -23.607619387904805,
    "p95": 31.291039688741023
   },
   "max_drawdown_pct": {
    "p5": 21.247386134719463,
    "p50": 37.60540632972946,
    "p95": 57.16191413753266
   },
   "prob_mdd_gt_30": 0.735,
   "approximation": "겹친 보유 무시 — 거래를 한 줄로 세워 복리"
  },
  "concentration": {
   "total_net_pnl": -2798654.426992518,
   "by_code": [
    {
     "k": 1,
     "removed": [
      "006340"
     ],
     "removed_pnl": 2285504.3761109994,
     "net_pnl_excluding": -5084158.803103518,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "006340",
      "001820"
     ],
     "removed_pnl": 3322165.9181909994,
     "net_pnl_excluding": -6120820.345183518,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "006340",
      "001820",
      "003010"
     ],
     "removed_pnl": 4187754.1162984995,
     "net_pnl_excluding": -6986408.543291017,
     "sign_flipped": false
    }
   ],
   "by_date": [
    {
     "k": 1,
     "removed": [
      "2026-05-07"
     ],
     "removed_pnl": 1999020.3963609997,
     "net_pnl_excluding": -4797674.823353518,
     "sign_flipped": false
    },
    {
     "k": 2,
     "removed": [
      "2026-05-07",
      "2026-05-28"
     ],
     "removed_pnl": 3213002.0679989997,
     "net_pnl_excluding": -6011656.494991518,
     "sign_flipped": false
    },
    {
     "k": 3,
     "removed": [
      "2026-05-07",
      "2026-05-28",
      "2026-03-06"
     ],
     "removed_pnl": 3977227.7081989995,
     "net_pnl_excluding": -6775882.135191517,
     "sign_flipped": false
    }
   ]
  }
 },
 "criteria": [
  {
   "metric": "sharpe",
   "threshold": 0.5,
   "direction": "min",
   "value": -0.8243005627849868,
   "passed": false,
   "note": null
  },
  {
   "metric": "max_drawdown_pct",
   "threshold": 30.0,
   "direction": "max",
   "value": 38.22630738168641,
   "passed": false,
   "note": null
  }
 ]
}, holdout: realHoSummary } })
