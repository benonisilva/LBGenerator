import sys
import logging
from threading import Thread

from sqlalchemy import and_
from sqlalchemy import insert
from sqlalchemy import update
from sqlalchemy import delete
from ...perf_profile import pprofile
from sqlalchemy.util import KeyedTuple
from sqlalchemy.orm.state import InstanceState

from ... import config
from ...lib import utils
from ...lib import cache
from ..index import Index
from .. import file_entity
from .. import document_entity
from . import CustomContextFactory
from ..entities import LBIndexError
from ...lib.lb_exception import LbException
from liblightbase.lbdoc.doctree import DocumentTree

log=logging.getLogger()


class DocumentContextFactory(CustomContextFactory):
    """Document Factory Methods.
    """

    def __init__(self, request, next_id_fn=None):
        super(DocumentContextFactory, self).__init__(request)

        # NOTE: Liblightbase.lbbase.Base object! By John Doe
        base=self.get_base()

        # NOTE: LBDoc_<base> object (mapped ORM entity)! By John Doe
        self.entity=document_entity(self.base_name,
            next_id_fn=next_id_fn,
            **base.relational_fields)

        # NOTE: LBFile_<base> object (mapped ORM entity)! By John Doe
        self.file_entity=file_entity(self.base_name)

        # NOTE: Index object! By John Doe
        self.index=Index(base, self.get_full_document)

    def create_files(self, member, files):
        """Create files (actually update id_doc, because file already exists)
        in database.

        @param files: List of file id's to create in database.
        """

        if len(files) > 0:
            stmt=update(self.file_entity.__table__).where(
                self.file_entity.__table__.c.id_file.in_(files))\
                .values(id_doc=member.id_doc)
            self.session.execute(stmt)

    def delete_files(self, member, files):
        """Will delete files that are not present in document.

        @param member: LBDoc_<base> object (mapped ORM entity).
        @param files: List of files ids present in document.
        """

        where_clause=[(self.file_entity.__table__.c.id_doc==member.id_doc)]
        if len(files) > 0:
            notin_clause=self.file_entity.__table__.c.id_file.notin_(files)
            where_clause.append(notin_clause)
            where_clause=and_(*where_clause)
            stmt=delete(self.file_entity.__table__).where(where_clause)
        else:
            stmt=delete(self.file_entity.__table__).where(*where_clause)

        self.session.execute(stmt)

    def create_member(self, data):
        """ 
        @param data: dictionary at the format {column_name: value}.
        Receives the data to INSERT at database (table lb_doc_<base>).
        Here the document will be indexed, and files within it will be created.
        """

        member=self.entity(**data)
        self.session.add(member)
        self.create_files(member, data['__files__'])
        for name in data:
            setattr(member, name, data[name])

        # NOTE: Now commits and closes session in the view instead of here
        # flush() pushes operations to DB's buffer - DCarv
        self.session.flush()
        self.session.commit()

        if self.index.is_indexable:
            Thread(
                target=self.async_create_member, 
                args=(
                    data, self.session
                )
            ).start()
        return member

    def async_create_member(self, data, session):
        """Called as a process. This method will update dt_idx in case 
        of success while asyncronous indexing.
        """

        ok=False
        try:
            ok, data=self.index.create(data)
        except Exception as e:
            log.debug("Problem creating in the index!\n%s", e)

        if ok:
            datacopy=data.copy()
            data.clear()
            data['document']=datacopy['document']
            data['dt_idx']=datacopy['dt_idx']
            stmt=update(self.entity.__table__).where(
                self.entity.__table__.c.id_doc == datacopy['id_doc'])\
                .values(**data)
            session.begin()
            try:
                session.execute(stmt)
            except:
                pass
            finally:

                # NOTE: Se não fecharmos a conexão aqui os registros ficam
                # locados e vai travar a próxima requisição! By Questor
                session.flush()
                session.commit()
                session.close()

    def update_member(self, member, data, index=True, alter_files=True):
        """Receives the data to UPDATE at database 
        (table lb_doc_<base>). Here the document will be indexed, files 
        within it will be created, and files that are not in document 
        will be deleted.

        @param member: LBDoc_<base> object (mapped ORM entity).
        @param data: dictionary at the format {column_name: value}.
        @param index: Flag that indicates the need of indexing the
        document. 
        """

        if alter_files:
            self.delete_files(member, data['__files__'])
            self.create_files(member, data['__files__'])

        data.pop('__files__')
        stmt=update(self.entity.__table__).where(
            self.entity.__table__.c.id_doc == data['id_doc'])\
            .values(**data)

        self.session.execute(stmt)
        self.session.flush()
        self.session.commit()

        if index and self.index.is_indexable:
            Thread(
                target=self.async_update_member, 
                args=(
                    data['id_doc'], 
                    data, 
                    self.session
                )
            ).start()

        # NOTE: Clear cache! By John Doe
        cache.clear_collection_cache(self.base_name)

        return member

    def async_update_member(self, id, data, session):
        """Called as a process. This method will update dt_idx in case 
        of success while asyncronous indexing.
        """

        ok=False
        try:
            ok, data=self.index.update(id, data, session)
        except Exception as e:
            log.debug("Problem updating in the index!\n%s", e)

        if ok:
            datacopy=data.copy()
            data.clear()
            data['document']=datacopy['document']
            data['dt_idx']=datacopy['dt_idx']
            stmt=update(self.entity.__table__).where(
                self.entity.__table__.c.id_doc == datacopy['id_doc'])\
                .values(**data)
            session.begin()
            try:
                session.execute(stmt)
            except:
                pass
            finally:

                # NOTE: Se não fecharmos a conexão aqui os registros ficam
                # locados e vai travar a próxima requisição! By Questor
                session.flush()
                session.commit()
                session.close()

    # TODO: Rever o comportamento descrito abaixo! By Questor
    def delete_member(self, id):
        """Query the document object, verify the flag "dt_del". If 
        setted, that means that this document was deleted once, but 
        it's index was not successfull deleted. So we delete the 
        document. If not, will try to delete it's index and document. 
        In case of failure, will SET all columns to NULL and clear 
        document, leaving only it's metadata.

        @param id: primary key (int) of document.
        """

        stmt1=delete(self.entity.__table__).where(
            self.entity.__table__.c.id_doc == id)
        stmt2=delete(self.file_entity.__table__).where(
            self.file_entity.__table__.c.id_doc == id)
        result=self.session.execute(stmt1)
        self.session.execute(stmt2)

        # NOTE: Now commits and closes session in the view instead of here
        # flush() pushes operations to DB's buffer - DCarv
        self.session.flush()
        self.session.commit()

        if self.index.is_indexable:
            Thread(
                target=self.async_delete_member, 
                args=(
                    id, 
                    self.session
                )
            ).start()

        # NOTE: Clear cache! By John Doe
        cache.clear_collection_cache(self.base_name)

        # NOTE: Returns the ResultProxy to check if something was deleted!
        # By John Doe
        return result

    # NOTE: Deleta no ES! By John Doe
    def async_delete_member(self, id, session):

        ok=False
        try:
            ok, data=self.index.delete(id)
        except Exception as e:
            log.debug("Problem deleting in the index!\n%s", e)

        if ok:
            stmt=insert(LBIndexError.__table__).values(**data)
            session.begin()
            try:
                session.execute(stmt)
            except:
                pass
            finally:

                # NOTE: Se não fecharmos a conexão aqui os registros ficam
                # locados e vai travar a próxima requisição! By Questor
                session.flush()
                session.commit()
                session.close()

    def get_full_documents(self, list_id_doc, members, session=None):
        """Pesquisa na tabela file e insere os textos extraídos nos 
        "docs" em members!

        @param list_id_doc: Lista com todos os "id_doc" para os quais 
        se quer inserir o texto extraído.
        @param members: Saída de uma consulta usando o SQLAlchemy.
        """

        if session is None:
            session=self.session

        file_cols=(
            self.file_entity.id_file,
            self.file_entity.id_doc,
            self.file_entity.filetext,
            self.file_entity.dt_ext_text
        )
        dbfiles=session.query(*file_cols).filter(
            self.file_entity.id_doc.in_(list_id_doc)
        ).all()
        members_file_id={}
        for index in range(0, len(dbfiles)):
            try:
                members_file_id[dbfiles[index].id_doc].append(index)
            except Exception as e:
                members_file_id[dbfiles[index].id_doc]=[index]

        # NOTE: Now commits and closes session in the view instead of here
        # flush() pushes operations to DB's buffer - DCarv
        session.flush()

        def prepare_file_text(list_items):
            members_filetext={}
            for index in list_items:
                members_filetext[str(dbfiles[index].id_file)]=dict(
                    filetext=dbfiles[index].filetext
                )
            return members_filetext

        for item in members:
            member_document=utils.json2object(item.document)
            if item.id_doc in members_file_id:
                self.put_doc_texts(
                    member_document, 
                    prepare_file_text(
                        members_file_id[item.id_doc]
                    )
                )

    def get_full_document(self, document, session=None):
        """ This method will return the document with files texts
        within it.
        """

        if session is None:
            session=self.session
        id=document['_metadata']['id_doc']

        file_cols=(
           self.file_entity.id_file,
           self.file_entity.filetext,
           self.file_entity.dt_ext_text)
        dbfiles=session.query(*file_cols).filter_by(id_doc=id).all()

        # NOTE I: Now commits and closes session in the view instead of here!
        # By John Doe
        # NOTE II: "flush()" pushes operations to DB's buffer - DCarv
        session.flush()

        files={}
        if dbfiles:
            for dbfile in dbfiles:
                files[dbfile.id_file]=dict(filetext=dbfile.filetext)

        return self.put_doc_texts(document, files)

    def put_doc_texts(self, document, files):
        """ This method will parse a document, find files within it,
        and then update each file (with text, if exists)
        """

        if type(document) is dict:
            _document=document.copy()
        elif type(document) is list:
            _document={document.index(i): i for i in document}
        for k, v in _document.items():
            if type(v) is dict and utils.is_file_mask(v):
                _file=files.get(v['id_file'])
                if _file: v.update(_file)
            elif type(v) is dict or type(v) is list:
                document[k]=self.put_doc_texts(v, files)
        return document

    def member_to_dict(self, member, fields=None):
        """
        @param member: LBDoc_<base> object (mapped ORM entity).

        Converts @member object to SQLAlchemy's KeyedTuple, and then to
        Python's dictionary. Will also prune the dictionary member, if
        user send some nodes on query.
        """
        try:
            dict_member=member._asdict()
        except AttributeError as e:

            # NOTE: Continue parsing! By John Doe
            log.debug("Error parsing as dict!\n%s", e)
            if not isinstance(member, KeyedTuple):
                member=self.member2KeyedTuple(member)

        # NOTE: Get document as dictionary object! By John Doe
        dict_member=member._asdict()['document']

        fields=getattr(self,'_query', {}).get('select')
        if fields and not '*' in fields:

            # NOTE: Will prune tree nodes. Dict_member can be None if method
            # could not find any fileds matching the nodes list! By John Doe
            dict_member=DocumentTree(dict_member).prune(nodes=fields)

        return dict_member

    def to_json(self, value, fields=None, wrap=True):
        obj=self.get_json_obj(value, fields, wrap)
        if getattr(self, 'single_member', None) is True and type(obj) is list:
            obj=obj[0]
        return utils.object2json(obj)

    def get_files_text_by_document_id(self, id_doc, close_session=True):
        """
        @param id_doc: id from document 
        @param close_session: If true, will close current session, 
        else will not.

        This method will return a dictonary in the format {id_file: filetext},
        with all docs referenced by @param: id_doc
        """

        # NOTE: Query documents! By John Doe
        files=self.session.query(self.file_entity.id_file,
            self.file_entity.filetext).filter_by(id_doc=id_doc).all() or []

        files={}
        for file_ in files:
            # NOTE: Build dictionary! John Doe

            files[file_.id_file]=file_.filetext

        return files
