// A bulk FoW inference kernel. Python RulesAdapter remains the independent oracle.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using U = uint64_t;
struct Board { U pieces[6], white, rights, turn, ep; };
struct History { U parent; int move; };
struct Candidate { Board board; U history; };
struct Entry { Board board; U parent, count; int move; };
struct View { Board contents; U mask; int captured, count; int moves[256]; };
static constexpr U NONE = UINT64_MAX;
static U bit(int s) { return U(1) << s; }
static U occupied(const Board& b) { U v=0; for(U p:b.pieces)v|=p; return v; }
static int pop(U& b) { int s=__builtin_ctzll(b); b&=b-1; return s; }
static int type(const Board& b,int s) { for(int t=0;t<6;++t)if(b.pieces[t]&bit(s))return t; return -1; }
static int enc(int f,int t,int p=0) { return f|(t<<6)|(p<<12); }
static bool same(const Board&a,const Board&b) { return std::memcmp(&a,&b,sizeof(Board))==0; }
struct Hash { size_t operator()(const Board& b) const { U h=0x9e3779b97f4a7c15ULL; const U*p=reinterpret_cast<const U*>(&b); for(size_t i=0;i<sizeof(Board)/8;++i)h^=p[i]+0x9e3779b97f4a7c15ULL+(h<<6)+(h>>2); return h; } };
struct Equal { bool operator()(const Board&a,const Board&b)const{return same(a,b);} };

struct AttackMasks {
    U knight[64]{}, king[64]{}, ray[64][8]{};
    AttackMasks(){
        const int nd[8][2]={{1,2},{2,1},{2,-1},{1,-2},{-1,-2},{-2,-1},{-2,1},{-1,2}};
        const int rd[8][2]={{1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}};
        for(int s=0;s<64;++s){int c=s%8,r=s/8;
            for(auto& d:nd){int x=c+d[0],y=r+d[1];if(x>=0&&x<8&&y>=0&&y<8)knight[s]|=bit(y*8+x);}
            for(int i=0;i<8;++i){int x=c+rd[i][0],y=r+rd[i][1];
                if(x>=0&&x<8&&y>=0&&y<8)king[s]|=bit(y*8+x);
                while(x>=0&&x<8&&y>=0&&y<8){ray[s][i]|=bit(y*8+x);x+=rd[i][0];y+=rd[i][1];}}
        }
    }
};
static const AttackMasks attacks;

static void addpawn(std::vector<int>& out,int f,int t) {
    if(t/8==0||t/8==7)for(int p:{2,3,4,5})out.push_back(enc(f,t,p));
    else out.push_back(enc(f,t));
}

static std::vector<int> moves(const Board& b,int color,bool sorted=true,bool first_only=false) {
    std::vector<int> out; out.reserve(64);
    U occ=occupied(b), own=color?b.white:occ&~b.white, enemy=occ^own;
    if(!(b.pieces[5]&own)||!(b.pieces[5]&enemy))return out;
    U pawns=b.pieces[0]&own;
    while(pawns){int f=pop(pawns),r=f/8,c=f%8,d=color?1:-1,t=f+d*8;
        if(t>=0&&t<64&&!(occ&bit(t))){addpawn(out,f,t);if(first_only)return out;int tt=t+d*8;if(r==(color?1:6)&&!(occ&bit(tt)))out.push_back(enc(f,tt));}
        for(int dc:{-1,1})if(c+dc>=0&&c+dc<8&&r+d>=0&&r+d<8){int to=t+dc;
            if((enemy&bit(to))||(color==int(b.turn)&&b.ep==U(to)&&!(occ&bit(to))&&r==(color?4:3))){addpawn(out,f,to);if(first_only)return out;}}
    }
    for(int kind=1;kind<6;++kind){U pieces=b.pieces[kind]&own;while(pieces){int f=pop(pieces);U targets=0;
        if(kind==1)targets=attacks.knight[f];
        else if(kind==5)targets=attacks.king[f];
        else for(int i=(kind==2?4:0);i<(kind==3?4:8);++i){
            U ray=attacks.ray[f][i],blockers=ray&occ;
            if(blockers){int stop=i%2?63-__builtin_clzll(blockers):__builtin_ctzll(blockers);ray^=attacks.ray[stop][i];}
            targets|=ray;
        }
        targets&=~own;while(targets){out.push_back(enc(f,pop(targets)));if(first_only)return out;}
    }}
    int k=color?4:60;
    if((b.pieces[5]&own&bit(k))){for(int rook:{k-4,k+3}){
        if(!(b.rights&b.pieces[3]&own&bit(rook)))continue;
        bool clear=true;for(int s=std::min(k,rook)+1;s<std::max(k,rook);++s)if(occ&bit(s))clear=false;
        if(clear){out.push_back(enc(k,k+(rook>k?2:-2)));if(first_only)return out;}
    }}
    if(sorted)std::sort(out.begin(),out.end());return out;
}

static void canonical(Board& b) {
    U occ=occupied(b);
    b.rights &= b.pieces[3];
    if(!(b.pieces[5]&b.white&bit(4)))b.rights&=~(bit(0)|bit(7));
    if(!(b.pieces[5]&~b.white&bit(60)))b.rights&=~(bit(56)|bit(63));
    if(b.ep<64){int ep=int(b.ep),from=ep+(b.turn?-8:8);U own=b.turn?b.white:occ&~b.white;bool valid=false;
        for(int dc:{-1,1}){int s=from+dc;if(s>=0&&s<64&&s/8==from/8&&(b.pieces[0]&own&bit(s)))valid=true;}
        if(!valid||(occ&bit(ep)))b.ep=64;
    }
}

static Board play(const Board& old,int action,int& captured) {
    Board b=old;int f=action&63,t=(action>>6)&63,p=action>>12,kind=type(b,f);U own=old.turn?old.white:occupied(old)&~old.white;
    int target=t;if(kind==0&&f%8!=t%8&&!(occupied(b)&bit(t)))target=t+(b.turn?-8:8);
    captured=(occupied(b)&bit(target))?target:-1;
    for(U& pieces:b.pieces)pieces&=~(bit(f)|bit(target));
    b.white&=~(bit(f)|bit(target));
    b.pieces[p?p-1:kind]|=bit(t);if(b.turn)b.white|=bit(t);
    b.rights&=~(bit(f)|bit(t));
    if(kind==5){b.rights&=b.turn?~(bit(0)|bit(7)):~(bit(56)|bit(63));
        if(std::abs(t-f)==2){int rook=f+(t>f?3:-4),dest=f+(t>f?1:-1);b.pieces[3]&=~bit(rook);b.pieces[3]|=bit(dest);b.white&=~bit(rook);if(b.turn)b.white|=bit(dest);}}
    b.ep=kind==0&&std::abs(t-f)==16?U((t+f)/2):64;b.turn=!b.turn;canonical(b);return b;
}

static U visible_from_moves(const Board& b,int viewer,const std::vector<int>& actions) {
    U occ=occupied(b), own=viewer?b.white:occ&~b.white, mask=own;
    // A captured king still has a view, but inference never advances a terminal view.
    for(int action:actions){int f=action&63,t=(action>>6)&63;mask|=bit(t);
        if(viewer==int(b.turn)&&b.ep==U(t)&&(b.pieces[0]&bit(f))&&f%8!=t%8&&!(occ&bit(t)))mask|=bit(t+(viewer?-8:8));}
    return mask;
}

static U visible(const Board& b,int viewer) {
    return visible_from_moves(b,viewer,moves(b,viewer,false));
}

struct MatchView {
    const View& view;
    std::array<U,512> allowed{};
    explicit MatchView(const View& v):view(v){for(int i=0;i<v.count;++i)allowed[v.moves[i]>>6]|=bit(v.moves[i]&63);}
};

static bool matches(const Board& b,const MatchView& expected,int viewer,int captured) {
    const View& v=expected.view;
    if(b.turn!=v.contents.turn||captured!=v.captured)return false;
    for(int k=0;k<6;++k)if((b.pieces[k]&v.mask)!=v.contents.pieces[k])return false;
    if((b.white&v.mask)!=v.contents.white)return false;
    auto actions=moves(b,viewer,false);
    if(viewer==int(b.turn)){
        if(actions.empty())return false;
        if(actions.size()!=size_t(v.count))return false;
        for(int a:actions)if(!(expected.allowed[a>>6]&bit(a&63)))return false;
    }else if(v.count||moves(b,int(b.turn),false,true).empty())return false;
    if(visible_from_moves(b,viewer,actions)!=v.mask)return false;
    return true;
}

struct Tracker {
    int viewer, ply=0; std::mt19937_64 rng;std::vector<Candidate> candidates;std::vector<History> histories;
    std::unordered_map<Board,U,Hash,Equal> indices;std::string error;U attempts=0,accepted=0;
    Tracker(Board b,int p,U seed):viewer(p),rng(seed){canonical(b);candidates.push_back({b,NONE});indices.emplace(b,0);}
};

extern "C" {
__declspec(dllexport) const char* zs_rules_id(){return "paper2021_fow_no_moves_draw_v1";}
__declspec(dllexport) void* zs_create(const Board* b,int viewer,U seed){try{return new Tracker(*b,viewer,seed);}catch(...){return nullptr;}}
__declspec(dllexport) void zs_destroy(Tracker* t){delete t;}
__declspec(dllexport) const char* zs_error(Tracker* t){return t->error.c_str();}
__declspec(dllexport) U zs_count(Tracker*t){return t->candidates.size();}
__declspec(dllexport) U zs_attempts(Tracker*t){return t->attempts;}
__declspec(dllexport) U zs_accepted(Tracker*t){return t->accepted;}
// Diagnostic ABI for builds with the identical Tracker layout and toolchain.
__declspec(dllexport) int zs_same_state(Tracker*a,Tracker*b){
    if(a->viewer!=b->viewer||a->ply!=b->ply||a->rng!=b->rng||a->attempts!=b->attempts||a->accepted!=b->accepted||
       a->candidates.size()!=b->candidates.size()||a->histories.size()!=b->histories.size()||a->indices.size()!=b->indices.size())return 0;
    for(size_t i=0;i<a->candidates.size();++i){const auto& x=a->candidates[i];const auto& y=b->candidates[i];
        if(!same(x.board,y.board)||x.history!=y.history)return 0;
        auto ai=a->indices.find(x.board),bi=b->indices.find(y.board);
        if(ai==a->indices.end()||bi==b->indices.end()||ai->second!=i||bi->second!=i)return 0;}
    for(size_t i=0;i<a->histories.size();++i)if(a->histories[i].parent!=b->histories[i].parent||a->histories[i].move!=b->histories[i].move)return 0;
    return 1;
}
__declspec(dllexport) int zs_validate(Tracker*t,const View*v){return matches(t->candidates[0].board,MatchView(*v),t->viewer,-1);}
__declspec(dllexport) int zs_update(Tracker*t,const View*v,int own_move,double seconds){
    try{
        auto began=std::chrono::steady_clock::now();auto rng=t->rng;U attempted=0,accepted=0;MatchView expected(*v);
        std::unordered_map<Board,Entry,Hash,Equal> next;next.reserve(t->candidates.size()*2);
        for(const Candidate& parent:t->candidates){
            auto actions=own_move>=0?std::vector<int>{own_move}:moves(parent.board,int(parent.board.turn));
            for(int move:actions){
                if((++attempted&1023)==0&&seconds>=0&&std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count()>=seconds)
                    throw std::runtime_error("native full-I deadline; no truncated update committed");
                int captured;Board b=play(parent.board,move,captured);
                if(int(parent.board.turn)==t->viewer)captured=-1;
                if(!matches(b,expected,t->viewer,captured))continue;++accepted;
                auto found=next.find(b);
                if(found==next.end())next.emplace(b,Entry{b,parent.history,1,move});
                else {Entry& e=found->second;++e.count;if(std::uniform_int_distribution<U>(1,e.count)(rng)==1){e.parent=parent.history;e.move=move;}}
            }
        }
        if(next.empty())throw std::runtime_error("empty full information set");
        std::vector<Entry> entries;entries.reserve(next.size());for(auto& pair:next)entries.push_back(pair.second);
        std::sort(entries.begin(),entries.end(),[](const Entry&a,const Entry&b){return std::memcmp(&a.board,&b.board,sizeof(Board))<0;});
        std::vector<Candidate> candidates;candidates.reserve(entries.size());
        std::vector<History> additions;additions.reserve(entries.size());
        std::unordered_map<Board,U,Hash,Equal> indices;indices.reserve(entries.size());
        for(auto&e:entries){indices.emplace(e.board,candidates.size());candidates.push_back({e.board,t->histories.size()+additions.size()});additions.push_back({e.parent,e.move});}
        if(seconds>=0&&std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count()>=seconds)throw std::runtime_error("native full-I deadline during deduplication");
        t->histories.insert(t->histories.end(),additions.begin(),additions.end());t->candidates.swap(candidates);t->indices.swap(indices);t->rng=rng;++t->ply;t->attempts=attempted;t->accepted=accepted;return 1;
    }catch(const std::exception&e){t->error=e.what();return 0;}
}
__declspec(dllexport) U zs_index(Tracker*t,const Board*source){Board b=*source;canonical(b);auto it=t->indices.find(b);return it==t->indices.end()?NONE:it->second;}
__declspec(dllexport) int zs_get(Tracker*t,U index,Board*b,int*path,int capacity){
    if(index>=t->candidates.size())return -1;const Candidate&c=t->candidates[index];*b=c.board;std::vector<int> actions;
    for(U h=c.history;h!=NONE;h=t->histories[h].parent)actions.push_back(t->histories[h].move);
    if(capacity>=int(actions.size()))std::reverse_copy(actions.begin(),actions.end(),path);return int(actions.size());
}
__declspec(dllexport) int zs_moves(const Board*b,int*out){auto result=moves(*b,int(b->turn));std::copy(result.begin(),result.end(),out);return int(result.size());}
__declspec(dllexport) int zs_has_moves(const Board*b){return !moves(*b,int(b->turn),false,true).empty();}
__declspec(dllexport) U zs_visible(const Board*b,int player){return visible(*b,player);}
__declspec(dllexport) void zs_observe(const Board*b,int player,int captured,View*out){
    auto actions=moves(*b,player);
    std::memset(out,0,sizeof(View));out->mask=visible_from_moves(*b,player,actions);out->captured=captured;
    out->contents.turn=b->turn;out->contents.white=b->white&out->mask;
    for(int i=0;i<6;++i)out->contents.pieces[i]=b->pieces[i]&out->mask;
    if(player==int(b->turn)){if(actions.size()>256){out->count=-1;return;}out->count=int(actions.size());std::copy(actions.begin(),actions.end(),out->moves);}
}
__declspec(dllexport) void zs_play(const Board*b,int move,Board*out,int*captured){*out=play(*b,move,*captured);}
__declspec(dllexport) int zs_fen(const Board*b,int halfmove,int fullmove,char*out,int capacity){
    std::string text;
    for(int rank=7;rank>=0;--rank){
        int empty=0;
        for(int file=0;file<8;++file){
            int square=rank*8+file,t=type(*b,square);
            if(t<0){++empty;continue;}
            if(empty){text+=char('0'+empty);empty=0;}
            text+=(b->white&bit(square)?"PNBRQK":"pnbrqk")[t];
        }
        if(empty)text+=char('0'+empty);
        if(rank)text+='/';
    }
    text+=b->turn?" w ":" b ";
    if(!b->rights)text+='-';
    else{
        if(b->rights&bit(7))text+='K';if(b->rights&bit(0))text+='Q';
        if(b->rights&bit(63))text+='k';if(b->rights&bit(56))text+='q';
    }
    text+=' ';
    if(b->ep==64)text+='-';else{text+=char('a'+b->ep%8);text+=char('1'+b->ep/8);}
    text+=' '+std::to_string(halfmove)+' '+std::to_string(fullmove);
    if(int(text.size()+1)>capacity)return -1;
    std::memcpy(out,text.c_str(),text.size()+1);return int(text.size());
}
}
